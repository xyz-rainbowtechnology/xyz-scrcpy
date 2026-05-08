#!/usr/bin/env python3
import fcntl
import os
import re
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path

from config_loader import load_config, save_config

BRAND_NAME = "RAINBOWTECHNOLOGY"
LOGO = [
    r"██╗  ██╗ ██╗   ██╗ ███████╗",
    r"╚██╗██╔╝ ╚██╗ ██╔╝ ╚══███╔╝",
    r" ╚███╔╝   ╚████╔╝    ███╔╝ ",
    r" ██╔██╗    ╚██╔╝    ███╔╝  ",
    r"██╔╝ ██╗    ██║    ███████╗",
    r"╚═╝  ╚═╝    ╚═╝    ╚══════╝",
]

RED, GREEN, MAGENTA, ORANGE, WHITE, RESET = (
    "\033[91m",
    "\033[38;5;118m",
    "\033[35m",
    "\033[38;5;208m",
    "\033[37m",
    "\033[0m",
)
NEON_PINK = "\033[38;5;213m"

ANSI_PATTERN = re.compile(r"\033\[[0-9;]*m")
ROOT_DIR = Path(__file__).resolve().parent.parent
LOCK_PATH = "/tmp/xyz_menu.lock"
INSTALLER_PATH = ROOT_DIR / "install_xyz.py"
SCRCPY_VENDOR_BIN = ROOT_DIR / "vendor" / "scrcpy"
LIME = "\033[38;5;154m"
MIC_BUS_NAME = "xyz-mic-input"


def get_key():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch += sys.stdin.read(2)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def visible_len(text):
    return len(ANSI_PATTERN.sub("", text))


def center_line(text, width):
    pad = max(0, (width - visible_len(text)) // 2)
    return (" " * pad) + text


def trunc_text(text, max_len):
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return "." * max_len
    return text[: max_len - 3] + "..."


def terminal_width():
    return max(40, min(120, shutil.get_terminal_size(fallback=(80, 24)).columns - 2))


def normalize_alias(alias):
    clean = re.sub(r"[^a-zA-Z0-9._-]", "-", str(alias).strip())
    clean = re.sub(r"-{2,}", "-", clean).strip("-")
    return clean or "xyz-scrcpy"


def prompt_text_input(prompt, default):
    sys.stdout.write("\n")
    sys.stdout.flush()
    value = input(f"{prompt} [{default}]: ").strip()
    return value if value else default


def sync_alias_launcher(alias):
    if not INSTALLER_PATH.exists():
        return False
    try:
        subprocess.run(
            [
                "python3",
                str(INSTALLER_PATH),
                "--action",
                "sync-alias",
                "--alias",
                alias,
                "--yes",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def has_audio_pending(cfg):
    return any(
        [
            str(cfg.get("audio_target", "host")) != str(cfg.get("applied_audio_target", "host")),
            bool(cfg.get("active_recall", False)) != bool(cfg.get("applied_active_recall", False)),
            bool(cfg.get("microphone_bus", False)) != bool(cfg.get("applied_microphone_bus", False)),
        ]
    )


def normalize_audio_preferences(cfg):
    normalized = dict(cfg)
    if bool(normalized.get("active_recall", False)) and str(normalized.get("audio_target", "host")).lower() == "device":
        # Active Recall uses Android microphone capture, which requires host-side audio enabled.
        normalized["audio_target"] = "host"
    return normalized


def list_devices():
    try:
        raw = subprocess.check_output(["adb", "devices"], text=True).splitlines()
        serials = [line.split()[0] for line in raw if line.strip().endswith("device") and not line.startswith("List")]
        devices = []
        for serial in serials:
            model = subprocess.check_output(
                ["adb", "-s", serial, "shell", "getprop", "ro.product.model"],
                text=True,
            ).strip()
            devices.append({"serial": serial, "label": f"{model} ({serial})"})
        return devices
    except subprocess.SubprocessError:
        return []


def resolve_scrcpy_binary():
    if SCRCPY_VENDOR_BIN.exists() and os.access(SCRCPY_VENDOR_BIN, os.X_OK):
        return str(SCRCPY_VENDOR_BIN)
    return "scrcpy"


def scrcpy_supports_microphone():
    scrcpy_bin = resolve_scrcpy_binary()
    try:
        output = subprocess.check_output([scrcpy_bin, "--help"], text=True, stderr=subprocess.STDOUT)
    except (subprocess.SubprocessError, OSError):
        return False
    lowered = output.lower()
    return "--audio-source" in lowered and "mic" in lowered


def _pactl_short_entries(kind):
    output = subprocess.check_output(["pactl", "list", "short", kind], text=True)
    entries = []
    for line in output.splitlines():
        parts = line.split("\t")
        if not parts:
            continue
        entries.append(parts)
    return entries


def audio_input_exists(name):
    try:
        if sys.platform == "linux":
            if shutil.which("pactl") is None:
                return False
            source_entries = _pactl_short_entries("sources")
            source_names = [parts[1].strip() for parts in source_entries if len(parts) > 1]
            return name in source_names

        if sys.platform == "darwin":
            output = subprocess.check_output(["system_profiler", "SPAudioDataType"], text=True, stderr=subprocess.STDOUT)
            lowered = output.lower()
            return name.lower() in lowered

        if sys.platform.startswith("win"):
            output = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_SoundDevice | Select-Object -ExpandProperty Name",
                ],
                text=True,
                stderr=subprocess.STDOUT,
            )
            return name.lower() in output.lower()
    except (subprocess.SubprocessError, OSError):
        return False
    return False


def ensure_microphone_bus(enabled):
    if not enabled:
        return False
    if sys.platform.startswith("win"):
        if audio_input_exists(MIC_BUS_NAME):
            return True
        print("[WARN] Windows microphone bus requires a virtual audio cable (for example VB-CABLE).")
        print(f"[WARN] Create or rename a virtual input to '{MIC_BUS_NAME}', then select it as your recording input.")
        return False
    if sys.platform == "darwin":
        if audio_input_exists(MIC_BUS_NAME):
            return True
        print("[WARN] macOS microphone bus requires a virtual loopback driver (for example BlackHole).")
        print(f"[WARN] Create or rename an input device as '{MIC_BUS_NAME}', then route system audio to it.")
        return False
    if sys.platform != "linux":
        print("[WARN] Microphone bus is not supported on this OS yet.")
        return False
    if shutil.which("pactl") is None:
        print("[WARN] microphone_bus requires 'pactl' (PulseAudio/PipeWire).")
        return False
    try:
        modules = _pactl_short_entries("modules")
        primary_remap_module_id = ""
        duplicate_module_ids = []

        # Cleanup legacy implementation that created an extra output sink,
        # and collapse duplicate remap modules for xyz-mic-input.
        for parts in modules:
            mod_id = parts[0].strip()
            module_name = parts[1].strip() if len(parts) > 1 else ""
            args = parts[-1]
            if f"sink_name={MIC_BUS_NAME}-sink" in args:
                subprocess.run(
                    ["pactl", "unload-module", mod_id],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                continue
            if module_name == "module-remap-source" and f"source_name={MIC_BUS_NAME}" in args:
                if not primary_remap_module_id:
                    primary_remap_module_id = mod_id
                else:
                    duplicate_module_ids.append(mod_id)

        for mod_id in duplicate_module_ids:
            subprocess.run(
                ["pactl", "unload-module", mod_id],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        if audio_input_exists(MIC_BUS_NAME):
            return True

        # If a stale remap module exists but source is gone, unload and rebuild cleanly.
        if primary_remap_module_id:
            subprocess.run(
                ["pactl", "unload-module", primary_remap_module_id],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        default_sink = subprocess.check_output(["pactl", "get-default-sink"], text=True).strip()
        if not default_sink:
            print("[WARN] Could not detect default sink for microphone bus.")
            return False
        created = subprocess.run(
            [
                "pactl",
                "load-module",
                "module-remap-source",
                f"master={default_sink}.monitor",
                f"source_name={MIC_BUS_NAME}",
                f"source_properties=device.description={MIC_BUS_NAME}",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if created.returncode != 0:
            print("[WARN] Unable to create microphone bus module.")
            return False

        return audio_input_exists(MIC_BUS_NAME)
    except (subprocess.SubprocessError, OSError):
        print("[WARN] Unable to initialize microphone bus.")
        return False


def launch_scrcpy(serial, cfg):
    cfg = normalize_audio_preferences(cfg)
    audio_target = str(cfg.get("audio_target", "host")).lower()
    active_recall = bool(cfg.get("active_recall", False))
    microphone_bus = bool(cfg.get("microphone_bus", False))
    scrcpy_bin = resolve_scrcpy_binary()
    cmd = [scrcpy_bin, "-s", serial, "--render-driver=software"]
    if audio_target == "device":
        cmd.append("--no-audio")
    if active_recall:
        if scrcpy_supports_microphone():
            cmd.append("--audio-source=mic")
        else:
            print("[WARN] Microphone is not supported by current scrcpy version.")
    ensure_microphone_bus(microphone_bus)
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ))


def render_menu(opts, idx, width):
    border = "=" * width
    out = [
        center_line("[SPACE] [ENTER] [ESC]".center(width), width),
        center_line(f"{RED}{border}{RESET}", width),
        "",
    ]
    for line in LOGO:
        out.append(center_line(f"{GREEN}{line.center(width)}{RESET}", width))
    out.append("")
    for i, opt in enumerate(opts):
        label = trunc_text(opt, width - 4)
        if i == idx:
            line = f"> {ORANGE}{label}{RESET} <"
        else:
            line = label
        out.append(center_line(line, width))
    out.extend(
        [
            "",
            center_line(f"{GREEN}{border}{RESET}", width),
            center_line(f"{NEON_PINK}[{BRAND_NAME}]".center(width) + f"{RESET}", width),
            center_line(f"{GREEN}{border}{RESET}", width),
        ]
    )
    return out


def settings_screen(cfg):
    temp_cfg = dict(cfg)
    temp_cfg["command_alias"] = normalize_alias(temp_cfg.get("command_alias", "xyz-scrcpy"))
    temp_cfg["open_cooldown_seconds"] = int(temp_cfg.get("open_cooldown_seconds", 30) or 30)
    field_idx = 0
    field_meta = {
        "auto_start": {"kind": "bool", "label": "Auto-start monitor"},
        "auto_discover": {"kind": "bool", "label": "Auto-discover devices"},
        "open_cooldown_seconds": {
            "kind": "int",
            "label": "Open cooldown (seconds)",
            "min": 0,
            "max": 600,
            "step": 5,
            "prompt": "Enter open cooldown in seconds (0-600)",
        },
        "audio_target": {"kind": "enum_audio", "label": "Audio target"},
        "active_recall": {"kind": "bool", "label": "Active Recall"},
        "microphone_bus": {"kind": "bool", "label": f"Microphone Bus ({MIC_BUS_NAME})"},
        "pause_on_exit": {"kind": "bool", "label": "Pause on EXIT"},
        "exit_pause_minutes": {
            "kind": "int",
            "label": "Pause duration (minutes)",
            "min": 1,
            "max": 43200,
            "step": 10,
            "prompt": "Enter pause duration in minutes (1-43200)",
        },
        "command_alias": {
            "kind": "text",
            "label": "Command alias",
            "prompt": "Enter new command alias",
        },
    }
    sections = [
        ("Launch behavior", ["auto_start", "auto_discover", "open_cooldown_seconds"]),
        ("Audio", ["audio_target", "active_recall", "microphone_bus"]),
        ("Session / Pause", ["pause_on_exit", "exit_pause_minutes"]),
        ("General", ["command_alias"]),
    ]
    fields = [
        "auto_start",
        "auto_discover",
        "open_cooldown_seconds",
        "audio_target",
        "active_recall",
        "microphone_bus",
        "pause_on_exit",
        "exit_pause_minutes",
        "command_alias",
        "APPLY",
        "CANCEL",
    ]

    def clamp_int(value, min_value, max_value):
        return max(min_value, min(max_value, value))

    def format_field(name):
        if name == "audio_target":
            return f"{field_meta[name]['label']}: {str(temp_cfg.get(name, 'host')).upper()}"
        if name in {"active_recall", "microphone_bus", "auto_start", "auto_discover", "pause_on_exit"}:
            return f"{field_meta[name]['label']}: {'ON' if bool(temp_cfg.get(name, False)) else 'OFF'}"
        if name in {"open_cooldown_seconds", "exit_pause_minutes"}:
            range_hint = f"{field_meta[name]['min']}-{field_meta[name]['max']}"
            return f"{field_meta[name]['label']}: {temp_cfg.get(name)} [{range_hint}]"
        if name == "command_alias":
            return f"{field_meta[name]['label']}: {temp_cfg.get(name, 'xyz-scrcpy')}"
        if name == "APPLY":
            return "[Apply]"
        if name == "CANCEL":
            return "[Cancel]"
        return name

    def apply_fast_edit(name, key):
        meta = field_meta.get(name)
        if not meta:
            return
        kind = meta["kind"]
        if kind == "bool":
            temp_cfg[name] = not bool(temp_cfg.get(name, False))
            return
        if kind == "enum_audio":
            current = str(temp_cfg.get("audio_target", "host")).lower()
            temp_cfg["audio_target"] = "device" if current == "host" else "host"
            return
        if kind == "int":
            direction = 1 if key == "\x1b[C" else -1
            step = int(meta.get("step", 1))
            current = int(temp_cfg.get(name, meta.get("min", 0)) or meta.get("min", 0))
            updated = current + (step * direction)
            temp_cfg[name] = clamp_int(updated, int(meta.get("min", 0)), int(meta.get("max", 999999)))

    def apply_precise_edit(name):
        meta = field_meta.get(name)
        if not meta:
            return
        kind = meta["kind"]
        if kind == "text":
            os.system("clear")
            try:
                entered = prompt_text_input(meta["prompt"], temp_cfg.get(name, "xyz-scrcpy"))
            except EOFError:
                entered = temp_cfg.get(name, "xyz-scrcpy")
            temp_cfg[name] = normalize_alias(entered)
            return
        if kind == "int":
            os.system("clear")
            try:
                entered = prompt_text_input(meta["prompt"], str(temp_cfg.get(name, meta.get("min", 0))))
            except EOFError:
                entered = str(temp_cfg.get(name, meta.get("min", 0)))
            try:
                parsed = int(entered)
            except ValueError:
                parsed = int(temp_cfg.get(name, meta.get("min", 0)) or meta.get("min", 0))
            temp_cfg[name] = clamp_int(parsed, int(meta.get("min", 0)), int(meta.get("max", 999999)))
            return
        apply_fast_edit(name, "\x1b[C")

    while True:
        width = terminal_width()
        border = "=" * width
        lines = [
            center_line(f"{GREEN}{border}{RESET}", width),
            center_line(f"{MAGENTA}SETTINGS - HYBRID EDIT{RESET}", width),
            center_line(f"{GREEN}{border}{RESET}", width),
            "",
        ]
        selected = fields[field_idx]
        rendered_rows = []
        for title, group_fields in sections:
            rendered_rows.append((None, f"[{title}]"))
            for name in group_fields:
                rendered_rows.append((name, format_field(name)))
            rendered_rows.append((None, ""))
        rendered_rows.append((None, "[Actions]"))
        rendered_rows.append(("APPLY", format_field("APPLY")))
        rendered_rows.append(("CANCEL", format_field("CANCEL")))

        for name, row in rendered_rows:
            if name is None:
                if row:
                    lines.append(center_line(f"{MAGENTA}{trunc_text(row, width - 2)}{RESET}", width))
                else:
                    lines.append("")
                continue
            text = trunc_text(row, width - 4)
            changed = name in temp_cfg and temp_cfg.get(name) != cfg.get(name)
            if changed:
                text = f"{RED}{text}{RESET}"
            lines.append(center_line((f"> {text}" if name == selected else f"  {text}"), width))
        lines.append("")
        lines.append(center_line("[UP/DOWN] move [LEFT/RIGHT] quick edit [ENTER] precise/apply [ESC] back", width))
        os.system("clear")
        sys.stdout.write("\n".join(lines))
        sys.stdout.flush()

        key = get_key()
        if key == "\x1b[A":
            field_idx = (field_idx - 1) % len(fields)
        elif key == "\x1b[B":
            field_idx = (field_idx + 1) % len(fields)
        elif key in ("\x1b[C", "\x1b[D", " "):
            name = fields[field_idx]
            if name not in {"APPLY", "CANCEL"}:
                apply_fast_edit(name, key)
        elif key == "\r":
            name = fields[field_idx]
            if name == "APPLY":
                temp_cfg["command_alias"] = normalize_alias(temp_cfg["command_alias"])
                temp_cfg = normalize_audio_preferences(temp_cfg)
                save_config(temp_cfg)
                sync_alias_launcher(temp_cfg["command_alias"])
                return load_config(), "apply"
            elif name == "CANCEL":
                return cfg, "cancel"
            else:
                apply_precise_edit(name)
        elif key == "\x1b":
            return cfg, "cancel"


def activate_pause_on_exit(cfg):
    cfg["pause_active"] = True
    cfg["pause_wait_reconnect"] = True
    cfg["pause_seen_disconnect"] = False
    pause_minutes = int(cfg.get("exit_pause_minutes", 1440))
    cfg["pause_until_epoch"] = int(time.time()) + (max(1, pause_minutes) * 60)
    save_config(cfg)


def main():
    signal.signal(signal.SIGWINCH, lambda *_: None)
    lock_file = open(LOCK_PATH, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)

    idx = 0
    cfg = load_config()
    try:
        while True:
            width = terminal_width()
            devices = list_devices()
            device_labels = [d["label"] for d in devices]
            restart_label = "RESTART"
            if has_audio_pending(cfg):
                restart_label = f"{LIME}RESTART{RESET}"
            else:
                restart_label = f"{RED}RESTART{RESET}"
            opts = device_labels + ["SETTINGS", restart_label, "EXIT"]
            if idx >= len(opts):
                idx = 0

            os.system("clear")
            sys.stdout.write("\n".join(render_menu(opts, idx, width)))
            sys.stdout.flush()

            key = get_key()
            if key == "\x1b[A":
                idx = (idx - 1) % len(opts)
            elif key == "\x1b[B":
                idx = (idx + 1) % len(opts)
            elif key == "\r":
                selected = opts[idx]
                if selected == "EXIT":
                    if cfg.get("pause_on_exit"):
                        activate_pause_on_exit(cfg)
                    break
                if selected == "SETTINGS":
                    cfg, _ = settings_screen(cfg)
                    continue
                if "RESTART" in selected:
                    target_serial = cfg.get("last_device_serial")
                    if not target_serial and devices:
                        target_serial = devices[0]["serial"]
                    if target_serial:
                        cfg = normalize_audio_preferences(cfg)
                        subprocess.run(
                            ["pkill", "-f", f"scrcpy.*-s[[:space:]]*{target_serial}"],
                            check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        time.sleep(0.4)
                        launch_scrcpy(target_serial, cfg)
                        cfg["applied_audio_target"] = cfg.get("audio_target", "host")
                        cfg["applied_active_recall"] = bool(cfg.get("active_recall", False))
                        cfg["applied_microphone_bus"] = bool(cfg.get("microphone_bus", False))
                        cfg["last_device_serial"] = target_serial
                        save_config(cfg)
                        cfg = load_config()
                    continue
                match = re.search(r"\((.*?)\)$", selected)
                device_serial = match.group(1) if match else selected
                cfg = normalize_audio_preferences(cfg)
                launch_scrcpy(device_serial, cfg)
                cfg["applied_audio_target"] = cfg.get("audio_target", "host")
                cfg["applied_active_recall"] = bool(cfg.get("active_recall", False))
                cfg["applied_microphone_bus"] = bool(cfg.get("microphone_bus", False))
                cfg["last_device_serial"] = device_serial
                save_config(cfg)
                cfg = load_config()
            elif key == "\x1b":
                break
    finally:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
        os.system("clear")


if __name__ == "__main__":
    main()
