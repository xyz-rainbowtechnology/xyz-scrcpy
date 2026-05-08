import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install_xyz


class InstallerTests(unittest.TestCase):
    def test_normalize_alias(self):
        self.assertEqual(install_xyz.normalize_alias("my alias!!"), "my-alias")
        self.assertEqual(install_xyz.normalize_alias(""), "xyz-scrcpy")

    def test_launcher_path_linux(self):
        launcher = install_xyz.launcher_path("linux", Path("/tmp/bin"), "abc")
        self.assertEqual(str(launcher), "/tmp/bin/abc")

    def test_launcher_path_windows(self):
        launcher = install_xyz.launcher_path("windows", Path("C:/bin"), "abc")
        self.assertTrue(str(launcher).endswith("abc.cmd"))

    def test_alias_saved_and_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            install_dir = Path(td)
            install_xyz.save_alias_to_config(install_dir, "my custom alias")
            alias = install_xyz.read_installed_alias(install_dir)
            self.assertEqual(alias, "my-custom-alias")

    def test_sync_alias_replaces_old_launcher(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install_dir = root / "app"
            launcher_dir = root / "bin"
            install_dir.mkdir(parents=True)
            launcher_dir.mkdir(parents=True)
            (install_dir / "bin").mkdir()
            (install_dir / "bin" / "menu.py").write_text("print('ok')\n", encoding="utf-8")

            paths = {
                "install_dir": install_dir,
                "launcher_dir": launcher_dir,
                "service_file": root / "dummy.service",
            }

            install_xyz.save_alias_to_config(install_dir, "old-alias")
            old_launcher = install_xyz.launcher_path("linux", launcher_dir, "old-alias")
            install_xyz.write_launcher("linux", old_launcher, install_dir)
            self.assertTrue(old_launcher.exists())

            install_xyz.do_sync_alias(paths, "linux", "new-alias")
            new_launcher = install_xyz.launcher_path("linux", launcher_dir, "new-alias")
            self.assertTrue(new_launcher.exists())
            self.assertFalse(old_launcher.exists())

    def test_do_install_always_runs_clean_uninstall_first(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            paths = {
                "install_dir": root / "app",
                "launcher_dir": root / "bin",
                "service_file": root / "svc",
            }
            src = root / "src"
            src.mkdir()
            (src / "dummy.txt").write_text("x", encoding="utf-8")
            paths["launcher_dir"].mkdir(parents=True)

            with (
                patch("install_xyz.do_uninstall") as mock_uninstall,
                patch("install_xyz.copy_project") as mock_copy,
                patch("install_xyz.check_dependencies"),
                patch("install_xyz.install_service"),
                patch("install_xyz.open_initial_menu"),
                patch("install_xyz.read_installed_alias", return_value="xyz-scrcpy"),
                patch("install_xyz.write_launcher"),
                patch("install_xyz.save_alias_to_config"),
            ):
                install_xyz.do_install(paths, src, "linux", "xyz-scrcpy", True, False)
                mock_uninstall.assert_called_once()
                mock_copy.assert_called_once()

    def test_ask_yes_no_defaults_and_values(self):
        with patch("builtins.input", return_value=""):
            self.assertTrue(install_xyz.ask_yes_no("Enable service", default_yes=True))
        with patch("builtins.input", return_value="n"):
            self.assertFalse(install_xyz.ask_yes_no("Enable service", default_yes=True))

    def test_uninstall_removes_managed_orphan_launchers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            install_dir = root / "app"
            launcher_dir = root / "bin"
            service_file = root / "svc"
            install_dir.mkdir(parents=True)
            launcher_dir.mkdir(parents=True)
            (install_dir / "bin").mkdir(parents=True)
            (install_dir / "bin" / "launch_with_checks.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (install_dir / "config").mkdir(parents=True)
            (install_dir / "config" / "config.json").write_text(
                json.dumps({"command_alias": "main-alias"}),
                encoding="utf-8",
            )

            managed_primary = launcher_dir / "main-alias"
            managed_orphan = launcher_dir / "old-alias"
            unmanaged = launcher_dir / "not-related"
            marker = str(install_dir / "bin" / "launch_with_checks.sh")
            managed_primary.write_text(f"bash \"{marker}\"\n", encoding="utf-8")
            managed_orphan.write_text(f"bash \"{marker}\"\n", encoding="utf-8")
            unmanaged.write_text("echo hello\n", encoding="utf-8")

            paths = {
                "install_dir": install_dir,
                "launcher_dir": launcher_dir,
                "service_file": service_file,
            }

            with patch("install_xyz.stop_service"), patch("install_xyz.uninstall_service"):
                install_xyz.do_uninstall(paths, "linux")

            self.assertFalse(install_dir.exists())
            self.assertFalse(managed_primary.exists())
            self.assertFalse(managed_orphan.exists())
            self.assertTrue(unmanaged.exists())

    def test_safe_delete_repo_copy_guarded(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            (repo / "install_xyz.py").write_text("print('x')\n", encoding="utf-8")
            self.assertTrue(install_xyz._safe_delete_repo_copy(repo))
            self.assertFalse(repo.exists())

    def test_project_scripts_use_portable_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = Path(install_xyz.__file__).resolve().parent
            dst = root / "installed-copy"
            install_xyz.copy_project(src, dst)

            monitor_text = (dst / "bin" / "monitor.sh").read_text(encoding="utf-8")
            repair_text = (dst / "repair_xyz.sh").read_text(encoding="utf-8")
            syntax_text = (dst / "bin" / "test_syntax.py").read_text(encoding="utf-8")
            service_text = (dst / "systemd" / "scrcpy-auto.service").read_text(encoding="utf-8")

            self.assertNotIn("/home/cloud-xyz/Documentos/NEXUS/apps/github/xyz-scrcpy", monitor_text)
            self.assertNotIn("/home/cloud-xyz/Documentos/NEXUS/apps/github/xyz-scrcpy", repair_text)
            self.assertNotIn("/home/cloud-xyz/Documentos/NEXUS/apps/github/xyz-scrcpy", syntax_text)
            self.assertIn("%h/.local/share/xyz-scrcpy/bin/monitor.sh", service_text)


if __name__ == "__main__":
    unittest.main()
