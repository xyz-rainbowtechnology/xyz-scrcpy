#!/usr/bin/env python3
"""XYZ-scrcpy installer (multi-OS, semi-interactive)."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "xyz-scrcpy"
TASK_NAME = "XYZScrcpyMonitor"
DEFAULT_ALIAS = "xyz-scrcpy"


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True)


def run_cmd_quiet(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        check=False,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ask_choice(prompt: str, options: list[str], default: str | None = None) -> str:
    while True:
        suffix = f" [{'/'.join(options)}]"
        if default:
            suffix += f" (default: {default})"
        answer = input(f"{prompt}{suffix}: ").strip().lower()
        if not answer and default:
            return default
        if answer in options:
            return answer
        print("Invalid option. Try again.")


def ask_input(prompt: str, default: str | None = None) -> str:
    suffix = f" (default: {default})" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    if not answer and default:
        return default
    return answer


def ask_yes_no(prompt: str, default_yes: bool = True) -> bool:
    options = "Y/n" if default_yes else "y/N"
    answer = input(f"{prompt} ({options}): ").strip().lower()
    if not answer:
        return default_yes
    return answer in {"y", "yes"}


def normalize_alias(alias: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]", "-", alias.strip())
    clean = re.sub(r"-{2,}", "-", clean).strip("-")
    return clean or DEFAULT_ALIAS


def detect_paths(os_name: str, home: Path) -> dict[str, Path]:
    if os_name == "linux":
        install_dir = home / ".local" / "share" / APP_NAME
        launcher_dir = home / ".local" / "bin"
        service_path = home / ".config" / "systemd" / "user" / "scrcpy-auto.service"
        return {
            "install_dir": install_dir,
            "launcher_dir": launcher_dir,
            "service_file": service_path,
        }
    if os_name == "darwin":
        install_dir = home / "Library" / "Application Support" / APP_NAME
        launcher_dir = home / "bin"
        service_path = home / "Library" / "LaunchAgents" / "com.xyz.scrcpy.monitor.plist"
        return {
            "install_dir": install_dir,
            "launcher_dir": launcher_dir,
            "service_file": service_path,
        }
    appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    install_dir = appdata / APP_NAME
    launcher_dir = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    return {
        "install_dir": install_dir,
        "launcher_dir": launcher_dir,
        "service_file": appdata / f"{APP_NAME}.task.txt",
    }


def launcher_path(os_name: str, launcher_dir: Path, alias: str) -> Path:
    if os_name == "windows":
        return launcher_dir / f"{alias}.cmd"
    return launcher_dir / alias


def _is_managed_launcher(launcher_file: Path, install_dir: Path) -> bool:
    if not launcher_file.exists() or not launcher_file.is_file():
        return False
    marker = str(install_dir / "bin" / "launch_with_checks.sh")
    try:
        content = launcher_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return marker in content


def remove_managed_launchers(paths: dict[str, Path], os_name: str, primary_alias: str) -> None:
    launcher_dir = paths["launcher_dir"]
    install_dir = paths["install_dir"]
    primary_path = launcher_path(os_name, launcher_dir, primary_alias)

    # Remove the primary detected alias first.
    if primary_path.exists():
        primary_path.unlink()

    # Defensive cleanup: remove any leftover launchers managed by this install.
    if not launcher_dir.exists():
        return
    for entry in launcher_dir.iterdir():
        if entry == primary_path:
            continue
        if _is_managed_launcher(entry, install_dir):
            entry.unlink()


def copy_project(src_root: Path, dst_root: Path) -> None:
    ignore = shutil.ignore_patterns(
        ".git",
        ".github",
        "__pycache__",
        "*.pyc",
        ".cursor",
        ".claude",
        "agent-transcripts",
    )
    if dst_root.exists():
        shutil.rmtree(dst_root)
    shutil.copytree(src_root, dst_root, ignore=ignore)


def write_launcher(os_name: str, launcher: Path, install_dir: Path) -> None:
    launcher.parent.mkdir(parents=True, exist_ok=True)
    if os_name in ("linux", "darwin"):
        content = f"""#!/usr/bin/env bash
bash "{install_dir / 'bin' / 'launch_with_checks.sh'}"
"""
    else:
        content = f"""@echo off
bash "{install_dir / 'bin' / 'launch_with_checks.sh'}"
"""
    launcher.write_text(content, encoding="utf-8")
    if os_name in ("linux", "darwin"):
        launcher.chmod(0o755)


def config_path(install_dir: Path) -> Path:
    return install_dir / "config" / "config.json"


def read_installed_alias(install_dir: Path) -> str:
    cfg_path = config_path(install_dir)
    if not cfg_path.exists():
        return DEFAULT_ALIAS
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        return normalize_alias(str(data.get("command_alias", DEFAULT_ALIAS)))
    except (json.JSONDecodeError, OSError, ValueError):
        return DEFAULT_ALIAS


def save_alias_to_config(install_dir: Path, alias: str) -> None:
    cfg_path = config_path(install_dir)
    cfg = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cfg = {}
    cfg["command_alias"] = normalize_alias(alias)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def linux_service_content(install_dir: Path) -> str:
    monitor = install_dir / "bin" / "monitor.sh"
    log_path = install_dir / "config" / "scrcpy.log"
    return f"""[Unit]
Description=XYZ / Rainbowtechnology - scrcpy Auto-Monitor Service
After=network.target

[Service]
ExecStart=/bin/bash {monitor}
Restart=always
RestartSec=10
Environment=DISPLAY=:0
Environment=XDG_SESSION_TYPE=wayland
StandardOutput=append:{log_path}
StandardError=append:{log_path}

[Install]
WantedBy=default.target
"""


def mac_plist_content(install_dir: Path) -> str:
    monitor = install_dir / "bin" / "monitor.sh"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.xyz.scrcpy.monitor</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>{monitor}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
"""


def install_service(os_name: str, service_file: Path, install_dir: Path, enable_service: bool) -> None:
    if os_name == "linux":
        service_file.parent.mkdir(parents=True, exist_ok=True)
        service_file.write_text(linux_service_content(install_dir), encoding="utf-8")
        run_cmd(["systemctl", "--user", "daemon-reload"])
        if enable_service:
            run_cmd(["systemctl", "--user", "enable", "--now", "scrcpy-auto.service"])
        else:
            run_cmd(["systemctl", "--user", "disable", "scrcpy-auto.service"], check=False)
            run_cmd(["systemctl", "--user", "stop", "scrcpy-auto.service"], check=False)
        return
    if os_name == "darwin":
        service_file.parent.mkdir(parents=True, exist_ok=True)
        service_file.write_text(mac_plist_content(install_dir), encoding="utf-8")
        run_cmd(["launchctl", "unload", str(service_file)], check=False)
        run_cmd(["launchctl", "load", str(service_file)])
        return
    menu_script = install_dir / "bin" / "menu.py"
    run_cmd(
        [
            "schtasks",
            "/create",
            "/f",
            "/sc",
            "onlogon",
            "/tn",
            TASK_NAME,
            "/tr",
            f'python "{menu_script}"',
        ]
    )
    if not enable_service:
        run_cmd(["schtasks", "/end", "/tn", TASK_NAME], check=False)
    service_file.parent.mkdir(parents=True, exist_ok=True)
    service_file.write_text(TASK_NAME, encoding="utf-8")


def stop_service(os_name: str, service_file: Path) -> None:
    if os_name == "linux":
        run_cmd_quiet(["systemctl", "--user", "stop", "scrcpy-auto.service"])
        return
    if os_name == "darwin":
        run_cmd_quiet(["launchctl", "unload", str(service_file)])
        return
    run_cmd_quiet(["schtasks", "/end", "/tn", TASK_NAME])


def uninstall_service(os_name: str, service_file: Path) -> None:
    if os_name == "linux":
        run_cmd_quiet(["systemctl", "--user", "disable", "--now", "scrcpy-auto.service"])
        if service_file.exists():
            service_file.unlink()
        run_cmd_quiet(["systemctl", "--user", "daemon-reload"])
        return
    if os_name == "darwin":
        run_cmd_quiet(["launchctl", "unload", str(service_file)])
        if service_file.exists():
            service_file.unlink()
        return
    run_cmd_quiet(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
    if service_file.exists():
        service_file.unlink()


def check_dependencies(os_name: str) -> None:
    required = ["adb", "scrcpy"]
    required.insert(0, "python" if os_name == "windows" else "python3")
    missing = [dep for dep in required if shutil.which(dep) is None]
    if missing:
        print(f"Warning: Missing dependencies: {', '.join(missing)}")
        print("Installation will continue, but runtime may fail until dependencies are installed.")
    if os_name == "linux" and shutil.which("pactl") is None:
        print("Notice: 'pactl' not found. Microphone Bus feature (xyz-mic-input) will fallback gracefully.")


def run_post_install_checks(install_dir: Path) -> tuple[str, str]:
    check_script = install_dir / "bin" / "check_and_repair.sh"
    proc = subprocess.run(
        ["bash", str(check_script)],
        text=True,
        capture_output=True,
        check=False,
    )
    status = (proc.stdout or "").strip().splitlines()
    status_code = status[-1].strip() if status else "UNKNOWN"
    log_path = install_dir / "config" / "check.log"
    summary = f"Check result: {status_code}"
    if log_path.exists():
        summary += " | log: ./config/check.log"
    return status_code, summary


def show_check_log(install_dir: Path) -> None:
    log_path = install_dir / "config" / "check.log"
    if not log_path.exists():
        print("No check log generated.")
        return
    print("\n--- check.log (last 40 lines) ---")
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in lines[-120:]:
        if line.startswith("[") or "Ran " in line or line in {"OK", "FAILED"} or "Please report this issue" in line:
            print(line)
    print("--- end of check.log ---\n")


def open_initial_menu(os_name: str, install_dir: Path, prechecked_status: str | None = None) -> None:
    launcher = install_dir / "bin" / "launch_with_checks.sh"
    env_prefix = ""
    if prechecked_status:
        env_prefix = f"XYZ_CHECKS_ALREADY_DONE=1 XYZ_CHECKS_STATUS={prechecked_status} "
    if os_name == "linux":
        run_cmd(
            [
                "gnome-terminal",
                "--hide-menubar",
                "--geometry=40x18",
                "--title=XYZ Initial Menu",
                "--",
                "bash",
                "-lc",
                f"{env_prefix}XYZ_LAUNCHER_WINDOW=1 bash \"{launcher}\"",
            ],
            check=False,
        )
        return
    if prechecked_status:
        subprocess.run(
            ["bash", str(launcher)],
            check=False,
            text=True,
            env={**os.environ, "XYZ_CHECKS_ALREADY_DONE": "1", "XYZ_CHECKS_STATUS": prechecked_status},
        )
        return
    run_cmd(["bash", str(launcher)], check=False)


def do_install(
    paths: dict[str, Path],
    src_root: Path,
    os_name: str,
    alias: str,
    enable_service: bool,
    run_tests_and_log: bool,
) -> None:
    print(f"Installing to: {paths['install_dir']}")
    check_dependencies(os_name)
    print("Running clean install (removing previous installation first)...")
    do_uninstall(paths, os_name, remove_app_files=True, remove_repo_copy=False)
    previous_alias = read_installed_alias(paths["install_dir"])
    copy_project(src_root, paths["install_dir"])
    save_alias_to_config(paths["install_dir"], alias)
    launch_path = launcher_path(os_name, paths["launcher_dir"], alias)
    previous_path = launcher_path(os_name, paths["launcher_dir"], previous_alias)
    if previous_path != launch_path and previous_path.exists():
        previous_path.unlink()
    write_launcher(os_name, launch_path, paths["install_dir"])
    install_service(os_name, paths["service_file"], paths["install_dir"], enable_service)
    print("Install completed.")
    print(f"Launcher: {launch_path}")
    if os_name == "linux" and enable_service:
        print("Service started with: systemctl --user start scrcpy-auto.service")
    elif os_name == "linux":
        print("Service installed but left disabled by user choice.")

    if run_tests_and_log:
        print("Running tests and validations now. Please wait...")
        status, summary = run_post_install_checks(paths["install_dir"])
        print(summary)
        show_check_log(paths["install_dir"])
        if status == "FAIL_OPEN":
            print("Checks still failing after repair.")
            print("Please report in GitHub Issues: https://github.com/xyz-rainbow/xyz-scrcpy/issues")
        print("Opening initial mini terminal...")
        open_initial_menu(os_name, paths["install_dir"], prechecked_status=status)
    else:
        print("Tests skipped by user. Menu can still open in fail-open mode.")
        print("If issues appear, report in GitHub Issues: https://github.com/xyz-rainbow/xyz-scrcpy/issues")
        print("Opening initial mini terminal...")
        open_initial_menu(os_name, paths["install_dir"])


def _safe_delete_repo_copy(repo_dir: Path) -> bool:
    """Delete repository folder with safety rails."""
    repo_dir = repo_dir.resolve()
    home = Path.home().resolve()
    if repo_dir in (Path("/"), home) or repo_dir == home.parent:
        return False
    # Basic guard to ensure we only remove an expected repo directory.
    if not (repo_dir / "install_xyz.py").exists():
        return False
    shutil.rmtree(repo_dir)
    return True


def do_uninstall(
    paths: dict[str, Path],
    os_name: str,
    remove_app_files: bool = True,
    remove_repo_copy: bool = False,
    repo_dir: Path | None = None,
) -> None:
    print("Stopping service/task first...")
    stop_service(os_name, paths["service_file"])
    print("Removing service/task from startup...")
    uninstall_service(os_name, paths["service_file"])
    alias = read_installed_alias(paths["install_dir"])
    remove_managed_launchers(paths, os_name, alias)
    if remove_app_files and paths["install_dir"].exists():
        shutil.rmtree(paths["install_dir"])
    elif not remove_app_files:
        print("Installed app files were kept by user choice.")
    if remove_repo_copy and repo_dir:
        if _safe_delete_repo_copy(repo_dir):
            print(f"Repository copy removed: {repo_dir}")
        else:
            print("Repository removal skipped by safety checks.")
    print("Uninstall completed.")


def do_sync_alias(paths: dict[str, Path], os_name: str, alias: str) -> None:
    install_dir = paths["install_dir"]
    if not install_dir.exists():
        print("Install directory not found. Run install first.")
        return
    previous_alias = read_installed_alias(install_dir)
    old_path = launcher_path(os_name, paths["launcher_dir"], previous_alias)
    new_path = launcher_path(os_name, paths["launcher_dir"], alias)
    if old_path != new_path and old_path.exists():
        old_path.unlink()
    save_alias_to_config(install_dir, alias)
    write_launcher(os_name, new_path, install_dir)
    print(f"Alias synced: {alias}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XYZ-scrcpy multi-OS installer")
    parser.add_argument(
        "--action",
        choices=["install", "uninstall", "remove", "sync-alias"],
        help="Run without interactive action prompt.",
    )
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt.")
    parser.add_argument("--alias", help="Custom launcher alias/command name.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os_name = platform.system().lower()
    if os_name not in {"linux", "darwin", "windows"}:
        print(f"Unsupported OS: {os_name}")
        return 1

    src_root = Path(__file__).resolve().parent
    paths = detect_paths(os_name, Path.home())

    action = args.action
    if not action:
        action = "install" if ask_yes_no("Install now", default_yes=True) else "uninstall"
    if action == "remove":
        action = "uninstall"

    if not args.yes:
        confirm = ask_choice(f"Confirm '{action}'", ["y", "n"], default="y")
        if confirm != "y":
            print("Aborted by user.")
            return 0

    try:
        if action in ("install", "sync-alias"):
            detected_alias = read_installed_alias(paths["install_dir"])
            if args.alias:
                alias = normalize_alias(args.alias)
            elif args.action:
                alias = detected_alias
            else:
                alias = normalize_alias(ask_input("Launcher alias", detected_alias))
            if action == "install":
                if args.yes:
                    enable_service = True
                    run_tests_and_log = True
                else:
                    enable_service = ask_yes_no("Enable service", default_yes=True)
                    run_tests_and_log = ask_yes_no("Run tests and view log", default_yes=True)
                do_install(paths, src_root, os_name, alias, enable_service, run_tests_and_log)
            else:
                do_sync_alias(paths, os_name, alias)
        else:
            if args.yes:
                remove_files = True
                remove_repo_copy = False
            else:
                remove_files = ask_yes_no("Delete installed app files", default_yes=False)
                remove_repo_copy = ask_yes_no("Delete current repository copy", default_yes=False)
            do_uninstall(
                paths,
                os_name,
                remove_app_files=remove_files,
                remove_repo_copy=remove_repo_copy,
                repo_dir=src_root,
            )
    except subprocess.CalledProcessError as exc:
        print(f"Command failed: {' '.join(exc.cmd)}")
        return 1
    except Exception as exc:  # pylint: disable=broad-except
        print(f"Unexpected error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
