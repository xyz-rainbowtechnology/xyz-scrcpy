import unittest
from unittest.mock import patch

import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))

import config_loader  # noqa: E402
import menu  # noqa: E402


class AudioConfigTests(unittest.TestCase):
    def test_resolve_scrcpy_binary_prefers_vendor(self):
        with tempfile.TemporaryDirectory() as td:
            fake_vendor = Path(td) / "scrcpy"
            fake_vendor.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            fake_vendor.chmod(0o755)
            with patch("menu.SCRCPY_VENDOR_BIN", fake_vendor):
                self.assertEqual(menu.resolve_scrcpy_binary(), str(fake_vendor))

    def test_resolve_scrcpy_binary_falls_back_to_path(self):
        with tempfile.TemporaryDirectory() as td:
            fake_vendor = Path(td) / "scrcpy-missing"
            with patch("menu.SCRCPY_VENDOR_BIN", fake_vendor):
                self.assertEqual(menu.resolve_scrcpy_binary(), "scrcpy")

    def test_defaults_include_audio_target(self):
        cfg = config_loader._normalize_config({})
        self.assertEqual(cfg["audio_target"], "host")
        self.assertEqual(cfg["sound"], "output")
        self.assertEqual(cfg["open_cooldown_seconds"], 30)
        self.assertFalse(cfg["active_recall"])
        self.assertFalse(cfg["microphone_bus"])

    def test_open_cooldown_normalization_bounds(self):
        cfg = config_loader._normalize_config({"open_cooldown_seconds": "45"})
        self.assertEqual(cfg["open_cooldown_seconds"], 45)

        cfg = config_loader._normalize_config({"open_cooldown_seconds": "invalid"})
        self.assertEqual(cfg["open_cooldown_seconds"], 30)

        cfg = config_loader._normalize_config({"open_cooldown_seconds": -10})
        self.assertEqual(cfg["open_cooldown_seconds"], 0)

        cfg = config_loader._normalize_config({"open_cooldown_seconds": 9999})
        self.assertEqual(cfg["open_cooldown_seconds"], 600)

    def test_migrate_sound_off_to_device_target(self):
        cfg = config_loader._normalize_config({"sound": "off"})
        self.assertEqual(cfg["audio_target"], "device")
        self.assertEqual(cfg["sound"], "off")

    def test_migrate_sound_output_to_host_target(self):
        cfg = config_loader._normalize_config({"sound": "output"})
        self.assertEqual(cfg["audio_target"], "host")
        self.assertEqual(cfg["sound"], "output")

    def test_normalize_audio_preferences_forces_host_when_active_recall(self):
        cfg = menu.normalize_audio_preferences({"audio_target": "device", "active_recall": True})
        self.assertEqual(cfg["audio_target"], "host")

    @patch("menu.ensure_microphone_bus")
    @patch("menu.scrcpy_supports_microphone", return_value=False)
    @patch("menu.print")
    @patch("menu.resolve_scrcpy_binary", return_value="/tmp/vendor/scrcpy")
    @patch("menu.subprocess.Popen")
    def test_launch_scrcpy_host_does_not_add_no_audio(self, mock_popen, _resolve, _print, _mic_support, _bus):
        menu.launch_scrcpy("ABC123", {"audio_target": "host", "active_recall": False, "microphone_bus": False})
        args = mock_popen.call_args[0][0]
        self.assertEqual(args[0], "/tmp/vendor/scrcpy")
        self.assertNotIn("--no-audio", args)

    @patch("menu.ensure_microphone_bus")
    @patch("menu.scrcpy_supports_microphone", return_value=False)
    @patch("menu.subprocess.Popen")
    def test_launch_scrcpy_device_adds_no_audio(self, mock_popen, _mic_support, _bus):
        menu.launch_scrcpy("ABC123", {"audio_target": "device", "active_recall": False, "microphone_bus": False})
        args = mock_popen.call_args[0][0]
        self.assertIn("--no-audio", args)

    @patch("menu.ensure_microphone_bus")
    @patch("menu.scrcpy_supports_microphone", return_value=True)
    @patch("menu.subprocess.Popen")
    def test_launch_scrcpy_forces_host_when_active_recall_on(self, mock_popen, _mic_support, _bus):
        menu.launch_scrcpy("ABC123", {"audio_target": "device", "active_recall": True, "microphone_bus": False})
        args = mock_popen.call_args[0][0]
        self.assertNotIn("--no-audio", args)
        self.assertIn("--audio-source=mic", args)

    @patch("menu.ensure_microphone_bus")
    @patch("menu.scrcpy_supports_microphone", return_value=True)
    @patch("menu.subprocess.Popen")
    def test_launch_scrcpy_adds_mic_flag_when_supported(self, mock_popen, _mic_support, _bus):
        menu.launch_scrcpy("ABC123", {"audio_target": "host", "active_recall": True, "microphone_bus": False})
        args = mock_popen.call_args[0][0]
        self.assertIn("--audio-source=mic", args)

    @patch("menu.ensure_microphone_bus")
    @patch("menu.scrcpy_supports_microphone", return_value=False)
    @patch("menu.print")
    @patch("menu.subprocess.Popen")
    def test_launch_scrcpy_skips_mic_flag_when_unsupported(self, mock_popen, _print, _mic_support, _bus):
        menu.launch_scrcpy("ABC123", {"audio_target": "host", "active_recall": True, "microphone_bus": False})
        args = mock_popen.call_args[0][0]
        self.assertNotIn("--audio-source=mic", args)

    @patch("menu.sys.platform", "linux")
    @patch("menu.shutil.which", return_value="/usr/bin/pactl")
    @patch("menu.subprocess.run")
    @patch(
        "menu.subprocess.check_output",
        side_effect=[
            "1\tmodule-device-restore\t\t\n",
            "33\txyz-mic-input\tmodule-remap-source.c\tfloat32le 2ch 48000Hz\tRUNNING\n",
        ],
    )
    def test_microphone_bus_reuses_existing_source(self, _check_output, mock_run, _which):
        self.assertTrue(menu.ensure_microphone_bus(True))
        mock_run.assert_not_called()

    @patch("menu.sys.platform", "darwin")
    @patch("menu.audio_input_exists", return_value=True)
    def test_microphone_bus_reuses_existing_source_on_macos(self, _exists):
        self.assertTrue(menu.ensure_microphone_bus(True))

    @patch("menu.sys.platform", "win32")
    @patch("menu.audio_input_exists", return_value=True)
    def test_microphone_bus_reuses_existing_source_on_windows(self, _exists):
        self.assertTrue(menu.ensure_microphone_bus(True))

    @patch("menu.ensure_microphone_bus", return_value=True)
    @patch("menu.scrcpy_supports_microphone", return_value=False)
    @patch("menu.subprocess.Popen")
    def test_launch_scrcpy_uses_default_env_when_bus_ready(self, mock_popen, _mic_support, _bus):
        menu.launch_scrcpy("ABC123", {"audio_target": "host", "active_recall": False, "microphone_bus": True})
        env = mock_popen.call_args.kwargs["env"]
        self.assertNotIn("PULSE_SINK", env)

    @patch("menu.sync_alias_launcher")
    @patch("menu.load_config", return_value={"ok": True})
    @patch("menu.save_config")
    @patch("menu.prompt_text_input", return_value="45")
    @patch("menu.get_key")
    @patch("menu.os.system")
    def test_settings_hybrid_edit_updates_cooldown_on_apply(
        self,
        _clear,
        mock_get_key,
        _prompt,
        mock_save,
        _load,
        _sync_alias,
    ):
        cfg = config_loader._normalize_config({})
        # Move to cooldown -> Enter precise edit -> move to APPLY -> Enter apply.
        mock_get_key.side_effect = ["\x1b[B", "\x1b[B", "\r"] + (["\x1b[B"] * 7) + ["\r"]

        _, result = menu.settings_screen(cfg)
        self.assertEqual(result, "apply")
        saved_cfg = mock_save.call_args[0][0]
        self.assertEqual(saved_cfg["open_cooldown_seconds"], 45)


if __name__ == "__main__":
    unittest.main()
