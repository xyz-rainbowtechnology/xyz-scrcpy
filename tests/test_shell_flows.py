import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CHECK_SCRIPT = ROOT / "bin" / "check_and_repair.sh"
LAUNCH_SCRIPT = ROOT / "bin" / "launch_with_checks.sh"


class ShellFlowTests(unittest.TestCase):
    def run_script(self, script, env=None, input_text=""):
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        return subprocess.run(
            ["bash", str(script)],
            text=True,
            input=input_text,
            capture_output=True,
            env=full_env,
            check=False,
        )

    def test_check_and_repair_pass_mode(self):
        proc = self.run_script(CHECK_SCRIPT, {"XYZ_TEST_MODE": "1", "XYZ_TEST_SCENARIO": "pass"})
        self.assertEqual(proc.returncode, 0)
        self.assertIn("PASS", proc.stdout)

    def test_check_and_repair_fail_open_mode(self):
        proc = self.run_script(CHECK_SCRIPT, {"XYZ_TEST_MODE": "1", "XYZ_TEST_SCENARIO": "fail"})
        self.assertEqual(proc.returncode, 0)
        self.assertIn("FAIL_OPEN", proc.stdout)

    def test_check_and_repair_pass_after_repair_mode(self):
        proc = self.run_script(CHECK_SCRIPT, {"XYZ_TEST_MODE": "1", "XYZ_TEST_SCENARIO": "repair-pass"})
        self.assertEqual(proc.returncode, 0)
        self.assertIn("PASS_AFTER_REPAIR", proc.stdout)

    def test_launch_with_checks_can_cancel_on_error(self):
        proc = self.run_script(
            LAUNCH_SCRIPT,
            {"XYZ_TEST_MODE": "1", "XYZ_TEST_SCENARIO": "fail", "XYZ_SKIP_MENU_EXEC": "1"},
            input_text="n\nn\n",
        )
        self.assertNotEqual(proc.returncode, 0)
        combined = (proc.stdout or "") + (proc.stderr or "")
        self.assertIn("Menu launch cancelled by user.", combined)

    def test_launch_with_checks_proceeds_on_error_when_confirmed(self):
        proc = self.run_script(
            LAUNCH_SCRIPT,
            {"XYZ_TEST_MODE": "1", "XYZ_TEST_SCENARIO": "fail", "XYZ_SKIP_MENU_EXEC": "1"},
            input_text="n\ny\n",
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("Test mode: menu execution skipped.", proc.stdout)


if __name__ == "__main__":
    unittest.main()
