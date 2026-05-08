#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECK_SCRIPT="$SCRIPT_DIR/check_and_repair.sh"
MENU_SCRIPT="$SCRIPT_DIR/menu.py"
LOG_FILE="$REPO_DIR/config/check.log"
FULL_LOG_FILE="$REPO_DIR/config/full-check.log"
FULL_PID_FILE="/tmp/xyz_full_checks.pid"
ISSUE_BASE_URL="https://github.com/xyz-rainbow/xyz-scrcpy/issues/new"

open_detached_menu_terminal() {
    if [ "${XYZ_LAUNCHER_WINDOW:-0}" = "1" ]; then
        return 1
    fi
    if [ "${XYZ_SKIP_MENU_EXEC:-0}" = "1" ]; then
        return 1
    fi
    if [ "$(uname -s)" != "Linux" ]; then
        return 1
    fi
    if [ -z "${DISPLAY:-}" ] || [ -z "${XDG_RUNTIME_DIR:-}" ]; then
        return 1
    fi
    if ! command -v gnome-terminal >/dev/null 2>&1; then
        return 1
    fi

    gnome-terminal \
        --hide-menubar \
        --geometry=40x18 \
        --title="XYZ Launcher" \
        -- \
        bash -lc "XYZ_LAUNCHER_WINDOW=1 bash \"$0\""
    return 0
}

start_background_full_checks() {
    if [ -f "$FULL_PID_FILE" ]; then
        old_pid="$(cat "$FULL_PID_FILE" 2>/dev/null || true)"
        if [ -n "$old_pid" ] && ps -p "$old_pid" > /dev/null 2>&1; then
            return
        fi
    fi
    (
        nohup env XYZ_CHECK_MODE=full XYZ_CHECK_LOG_FILE="$FULL_LOG_FILE" bash "$CHECK_SCRIPT" > /dev/null 2>&1 &
        echo $! > "$FULL_PID_FILE"
    ) >/dev/null 2>&1
}

open_prefilled_issue() {
    local log_snippet="" crash_snippet="" timing_snippet="" os_info="" scrcpy_info=""
    os_info="$(python3 - <<'PY'
import os
import platform

pretty = ""
try:
    with open("/etc/os-release", "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("PRETTY_NAME="):
                pretty = line.split("=", 1)[1].strip().strip('"')
                break
except OSError:
    pass
if not pretty:
    pretty = platform.system()
print(f"{pretty} | {platform.platform()}")
PY
)"
    scrcpy_info="$(scrcpy --version 2>/dev/null | head -n 1 || echo "scrcpy unknown")"
    if [ -f "$LOG_FILE" ]; then
        log_snippet="$(python3 - "$LOG_FILE" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
interesting = []
for line in lines[-120:]:
    if line.startswith("[") or "Traceback" in line or "FAILED" in line or "ERROR" in line:
        interesting.append(line)
trimmed = "\n".join(interesting[-40:]).strip()
print(trimmed)
PY
)"
        crash_snippet="$(python3 - "$LOG_FILE" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
keys = ("traceback", "exception", "error", "failed", "segmentation fault", "core dumped")
matches = [ln for ln in lines if any(k in ln.lower() for k in keys)]
print("\n".join(matches[-25:]).strip())
PY
)"
        timing_snippet="$(python3 - "$LOG_FILE" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
timing = [ln for ln in lines if "Timing:" in ln]
print("\n".join(timing[-5:]).strip())
PY
)"
    fi

    local issue_url
    issue_url="$(XYZ_ISSUE_LOG_SNIPPET="$log_snippet" XYZ_ISSUE_CRASH_SNIPPET="$crash_snippet" XYZ_ISSUE_TIMING_SNIPPET="$timing_snippet" XYZ_ISSUE_OS_INFO="$os_info" XYZ_ISSUE_SCRCPY_INFO="$scrcpy_info" python3 - <<'PY'
import urllib.parse
import os

title = "Fail-open detected during launcher checks"
body = (
    "## What happened\n"
    "Fail-open mode was triggered by launch checks.\n\n"
    "## Environment\n"
    "- Launcher: xyz-scrcpy\n"
    "- Check mode: fail-open\n\n"
    "## System info\n"
    "- OS: " + os.environ.get("XYZ_ISSUE_OS_INFO", "unknown") + "\n"
    "- " + os.environ.get("XYZ_ISSUE_SCRCPY_INFO", "scrcpy unknown") + "\n\n"
    "## Time log\n"
    "```\n"
    + os.environ.get("XYZ_ISSUE_TIMING_SNIPPET", "(no timing info found)") +
    "\n```\n\n"
    "## Crash context (sanitized)\n"
    "```\n"
    + os.environ.get("XYZ_ISSUE_CRASH_SNIPPET", "(no crash context found)") +
    "\n```\n\n"
    "## Sanitized log excerpt\n"
    "```\n"
    + os.environ.get("XYZ_ISSUE_LOG_SNIPPET", "(no log excerpt)") +
    "\n```\n"
)
params = urllib.parse.urlencode({"title": title, "body": body})
print("https://github.com/xyz-rainbow/xyz-scrcpy/issues/new?" + params)
PY
)"

    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$issue_url" >/dev/null 2>&1 || true
        echo "[INFO] Opened prefilled issue page in browser."
    else
        echo "[INFO] Open this prefilled issue URL manually:"
        echo "$issue_url"
    fi
}

if open_detached_menu_terminal; then
    exit 0
fi

if [ "${XYZ_CHECKS_ALREADY_DONE:-0}" = "1" ]; then
    status="${XYZ_CHECKS_STATUS:-PASS}"
    echo "[INFO] Reusing installer check result: $status"
else
    echo "[INFO] Running quick syntax checks..."
    status="$(env XYZ_CHECK_MODE=quick bash "$CHECK_SCRIPT" | tail -n 1)"
fi

case "$status" in
    PASS|PASS_AFTER_REPAIR)
        start_background_full_checks
        if [ -f "$FULL_LOG_FILE" ]; then
            echo "[INFO] Full test suite is running in background: $FULL_LOG_FILE"
        else
            echo "[INFO] Full test suite started in background."
        fi
        ;;
    FAIL_OPEN)
        echo "[WARNING] Automated checks are still failing."
        echo "[WARNING] Fail-open mode is available."
        echo "[WARNING] Please report with logs: https://github.com/xyz-rainbow/xyz-scrcpy/issues"
        echo "[WARNING] GitHub issue creation requires login; or email log to rainbow@rainbowtechnology.xyz"
        read -r -p "Open prefilled GitHub issue page now? (Y/n): " open_issue
        open_issue="${open_issue,,}"
        if [ -z "$open_issue" ] || [ "$open_issue" = "y" ] || [ "$open_issue" = "yes" ]; then
            open_prefilled_issue
        fi
        read -r -p "Open menu anyway despite errors? (Y/n): " open_anyway
        open_anyway="${open_anyway,,}"
        if [ -n "$open_anyway" ] && [ "$open_anyway" != "y" ] && [ "$open_anyway" != "yes" ]; then
            echo "[INFO] Menu launch cancelled by user."
            exit 1
        fi
        ;;
    *)
        echo "[WARNING] Unknown check status: $status"
        ;;
esac

if [ -f "$LOG_FILE" ]; then
    echo "[INFO] Check log: ./config/check.log"
fi

if [ "${XYZ_SKIP_MENU_EXEC:-0}" = "1" ]; then
    echo "[INFO] Test mode: menu execution skipped."
    exit 0
fi

echo "[INFO] Launching interactive menu..."
exec python3 "$MENU_SCRIPT"
