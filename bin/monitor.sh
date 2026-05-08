#!/bin/bash
# __  ____   _______
# \ \/ /\ \ / /__  /
#  \  /  \ V /  / / 
#  /  \   | |  / /_ 
# /_/\_\  |_| /____|
# #xyz-rainbowtechnology
# #rainbowtechnology.xyz
# #rainbow.xyz
# #rainbow@rainbowtechnology.xyz
# #i-love-you
# #You're not supposed to see this!

set -u

PID_FILE="/tmp/xyz_monitor.pid"
SERIAL_STATE_FILE="/tmp/xyz_monitor_serials.state"
LAST_OPEN_EPOCH_FILE="/tmp/xyz_monitor_last_open.epoch"
LAST_BLOCK_REASON_FILE="/tmp/xyz_monitor_last_block_reason.state"
OPEN_COOLDOWN_SECONDS="${OPEN_COOLDOWN_SECONDS:-}"
OPEN_COOLDOWN_FROM_ENV=0
if [ -n "${OPEN_COOLDOWN_SECONDS+x}" ] && [ -n "$OPEN_COOLDOWN_SECONDS" ]; then
    OPEN_COOLDOWN_FROM_ENV=1
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MENU_SCRIPT="$REPO_DIR/bin/menu.py"
CFG_LOADER="$REPO_DIR/bin/config_loader.py"
PYTHONPATH_DIR="$REPO_DIR/bin"
MONITOR_BLOCK_REASON=""

if [ "${MONITOR_TEST_MODE:-0}" != "1" ]; then
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null; then
            exit 0
        fi
    fi
    echo $$ > "$PID_FILE"
fi

cleanup() {
    if [ "${MONITOR_TEST_MODE:-0}" != "1" ]; then
        rm -f "$PID_FILE"
        rm -f "$SERIAL_STATE_FILE"
    fi
}
trap cleanup EXIT

log_message() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1"
}

log_block_reason_if_changed() {
    local reason="$1"
    local previous=""

    [ -n "$reason" ] || return
    if [ -f "$LAST_BLOCK_REASON_FILE" ]; then
        previous="$(<"$LAST_BLOCK_REASON_FILE")"
    fi
    if [ "$previous" != "$reason" ]; then
        log_message "[INFO] Popup blocked: $reason"
        printf '%s' "$reason" > "$LAST_BLOCK_REASON_FILE"
    fi
}

clear_block_reason_state() {
    rm -f "$LAST_BLOCK_REASON_FILE"
}

last_open_epoch() {
    local value=""
    if [ -f "$LAST_OPEN_EPOCH_FILE" ]; then
        value="$(<"$LAST_OPEN_EPOCH_FILE")"
    fi
    if [[ "$value" =~ ^[0-9]+$ ]]; then
        echo "$value"
    else
        echo 0
    fi
}

touch_last_open_epoch() {
    date +%s > "$LAST_OPEN_EPOCH_FILE"
}

is_open_cooldown_active() {
    local now last delta
    now="$(date +%s)"
    last="$(last_open_epoch)"
    [ "$last" -gt 0 ] || return 1
    delta=$((now - last))
    if [ "$delta" -lt "$OPEN_COOLDOWN_SECONDS" ]; then
        MONITOR_BLOCK_REASON="cooldown_active(${delta}s/${OPEN_COOLDOWN_SECONDS}s)"
        return 0
    fi
    return 1
}

resolve_open_cooldown_seconds() {
    local candidate=""
    local default_value=30

    if [ "${MONITOR_TEST_MODE:-0}" = "1" ] && [ -n "${TEST_OPEN_COOLDOWN_SECONDS:-}" ]; then
        candidate="${TEST_OPEN_COOLDOWN_SECONDS}"
    elif [ "$OPEN_COOLDOWN_FROM_ENV" = "1" ]; then
        candidate="$OPEN_COOLDOWN_SECONDS"
    else
        candidate="$(read_config_value open_cooldown_seconds)"
    fi

    if ! [[ "$candidate" =~ ^[0-9]+$ ]]; then
        candidate="$default_value"
    fi
    if [ "$candidate" -gt 600 ]; then
        candidate=600
    fi

    OPEN_COOLDOWN_SECONDS="$candidate"
}

validate_menu_syntax() {
    python3 -m py_compile "$MENU_SCRIPT" "$CFG_LOADER" > /dev/null 2>&1
}

read_config_value() {
    local key="$1"
    PYTHONPATH="$PYTHONPATH_DIR" python3 - "$key" <<'PY'
import json
import os
import sys
from config_loader import load_config, save_config

key = sys.argv[1]
cfg = load_config()
value = cfg.get(key, "")
if isinstance(value, bool):
    print("true" if value else "false")
else:
    print(value)
PY
}

read_serials_from_adb() {
    adb devices | awk '/device$/{print $1}' | paste -sd ',' -
}

count_serials() {
    local serials="$1"
    if [ -z "$serials" ]; then
        echo 0
        return
    fi
    awk -F',' '{print NF}' <<< "$serials"
}

first_serial() {
    local serials="$1"
    IFS=',' read -r first _ <<< "$serials"
    echo "$first"
}

load_previous_serials() {
    if [ "${MONITOR_TEST_MODE:-0}" = "1" ]; then
        echo "${TEST_PREV_SERIALS:-}"
        return
    fi
    if [ -f "$SERIAL_STATE_FILE" ]; then
        cat "$SERIAL_STATE_FILE"
    fi
}

save_current_serials() {
    local serials="$1"
    if [ "${MONITOR_TEST_MODE:-0}" = "1" ]; then
        return
    fi
    printf '%s' "$serials" > "$SERIAL_STATE_FILE"
}

update_pause_state_from_snapshots() {
    local prev_serials="$1"
    local curr_serials="$2"
    local device_count="$3"
    PYTHONPATH="$PYTHONPATH_DIR" python3 - "$prev_serials" "$curr_serials" "$device_count" <<'PY'
import sys
import time
from config_loader import load_config, save_config

prev_serials = sys.argv[1].strip()
curr_serials = sys.argv[2].strip()
device_count = int(sys.argv[3])
cfg = load_config()
now = int(time.time())

if cfg.get("pause_active"):
    auto_discover = bool(cfg.get("auto_discover", True))
    pause_until = int(cfg.get("pause_until_epoch", 0) or 0)
    wait_reconnect = bool(cfg.get("pause_wait_reconnect", False))
    seen_disconnect = bool(cfg.get("pause_seen_disconnect", False))
    prev_set = {x for x in prev_serials.split(",") if x}
    curr_set = {x for x in curr_serials.split(",") if x}

    # Reglas de contrato:
    # 1) Pause on EXIT activa la pausa.
    # 2) Con auto_discover ON, una reconexion valida levanta la pausa.
    # 3) Reconexion valida: hubo desconexion previa o cambio de conjunto de seriales.
    reconnect_event = bool(curr_set) and (seen_disconnect or (bool(prev_set) and curr_set != prev_set))

    if device_count == 0 and wait_reconnect:
        seen_disconnect = True
        cfg["pause_seen_disconnect"] = True

    if auto_discover and wait_reconnect and reconnect_event:
        cfg["pause_active"] = False
        cfg["pause_wait_reconnect"] = False
        cfg["pause_seen_disconnect"] = False
        cfg["pause_until_epoch"] = 0
    elif now >= pause_until and pause_until > 0:
        cfg["pause_active"] = False
        cfg["pause_wait_reconnect"] = False
        cfg["pause_seen_disconnect"] = False
        cfg["pause_until_epoch"] = 0

    save_config(cfg)
PY
}

evaluate_test_pause_state() {
    local prev_serials="$1"
    local curr_serials="$2"
    local pause_active="${TEST_PAUSE_ACTIVE:-false}"
    local wait_reconnect="${TEST_PAUSE_WAIT_RECONNECT:-false}"
    local seen_disconnect="${TEST_PAUSE_SEEN_DISCONNECT:-false}"
    local auto_discover="${TEST_AUTO_DISCOVER:-true}"

    if [ "$pause_active" = "true" ] && [ "$wait_reconnect" = "true" ] && [ "$auto_discover" = "true" ]; then
        if [ -z "$curr_serials" ]; then
            seen_disconnect="true"
        elif [[ "$seen_disconnect" = "true" || ( -n "$prev_serials" && "$prev_serials" != "$curr_serials" ) ]]; then
            pause_active="false"
            echo "RECONNECT_RESUME" >&2
        fi
    fi

    echo "$pause_active"
}

compute_terminal_geometry() {
    local device_count="$1"
    local cols=40
    local base_rows=18
    local extra_rows=0

    # Keep the target base size close to the requested visual dimensions,
    # then add one line per additional detected device.
    if [ "$device_count" -gt 1 ]; then
        extra_rows=$((device_count - 1))
    fi

    local rows=$((base_rows + extra_rows))
    echo "${cols}x${rows}"
}

is_monitor_or_scrcpy_active() {
    local serial="$1"
    MONITOR_BLOCK_REASON=""
    if [ "${MONITOR_TEST_MODE:-0}" = "1" ]; then
        if [ "${MONITOR_HAS_MENU_PROCESS:-0}" = "1" ]; then
            MONITOR_BLOCK_REASON="existing_menu_process"
            return 0
        fi
        if [ "${MONITOR_HAS_WINDOW:-0}" = "1" ] || [ "${MONITOR_HAS_SCRCPY:-0}" = "1" ]; then
            MONITOR_BLOCK_REASON="existing_monitor_or_scrcpy"
            return 0
        fi
        return 1
    fi

    # If any monitor terminal is already open, avoid opening more popups.
    if pgrep -f "XYZ Monitor -" > /dev/null; then
        MONITOR_BLOCK_REASON="existing_monitor_window"
        return 0
    fi

    # If menu.py is active in any terminal/session, avoid opening another popup.
    if pgrep -f "$MENU_SCRIPT" > /dev/null; then
        MONITOR_BLOCK_REASON="existing_menu_process"
        return 0
    fi

    # If scrcpy is already running (same device or any device), do not spawn popups.
    if [ -n "$serial" ] && pgrep -f "scrcpy.*-s[[:space:]]*$serial" > /dev/null; then
        MONITOR_BLOCK_REASON="existing_scrcpy_serial"
        return 0
    fi
    if pgrep -x scrcpy > /dev/null; then
        MONITOR_BLOCK_REASON="existing_scrcpy_any"
        return 0
    fi

    return 1
}

open_menu_terminal() {
    local geometry="$1"
    local title="$2"
    local os_name
    os_name="$(uname -s 2>/dev/null || echo Linux)"

    case "$os_name" in
        Linux)
            if command -v gnome-terminal > /dev/null 2>&1; then
                gnome-terminal --hide-menubar --geometry="$geometry" --title="$title" -- python3 "$MENU_SCRIPT"
                return 0
            fi
            if command -v x-terminal-emulator > /dev/null 2>&1; then
                x-terminal-emulator -geometry "$geometry" -title "$title" -e python3 "$MENU_SCRIPT"
                return 0
            fi
            if command -v xfce4-terminal > /dev/null 2>&1; then
                xfce4-terminal --geometry="$geometry" --title="$title" --command "python3 \"$MENU_SCRIPT\""
                return 0
            fi
            if command -v konsole > /dev/null 2>&1; then
                konsole --geometry "$geometry" --new-tab -e python3 "$MENU_SCRIPT"
                return 0
            fi
            if command -v xterm > /dev/null 2>&1; then
                cols="${geometry%x*}"
                rows="${geometry#*x}"
                xterm -geometry "${cols}x${rows}" -T "$title" -e python3 "$MENU_SCRIPT"
                return 0
            fi
            ;;
        Darwin)
            if command -v osascript > /dev/null 2>&1; then
                local escaped_menu_script
                escaped_menu_script="${MENU_SCRIPT//\"/\\\"}"
                osascript -e "tell application \"Terminal\" to do script \"python3 \\\"${escaped_menu_script}\\\"\""
                return $?
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*|Windows_NT)
            if command -v powershell.exe > /dev/null 2>&1; then
                powershell.exe -NoProfile -Command "Start-Process powershell -ArgumentList '-NoExit','-Command','python3 \"${MENU_SCRIPT}\"'"
                return $?
            fi
            ;;
    esac
    return 1
}

while true; do
    if [ "${MONITOR_TEST_MODE:-0}" = "1" ]; then
        CURRENT_SERIALS="${TEST_CURR_SERIALS:-${TEST_DEVICE_SERIAL:-}}"
    else
        CURRENT_SERIALS="$(read_serials_from_adb)"
    fi

    PREVIOUS_SERIALS="$(load_previous_serials)"
    DEVICE_COUNT="$(count_serials "$CURRENT_SERIALS")"
    DEVICE_SERIAL="$(first_serial "$CURRENT_SERIALS")"

    if [ "${MONITOR_TEST_MODE:-0}" = "1" ]; then
        AUTO_START="${TEST_AUTO_START:-true}"
        AUTO_DISCOVER="${TEST_AUTO_DISCOVER:-true}"
        PAUSE_ACTIVE="$(evaluate_test_pause_state "$PREVIOUS_SERIALS" "$CURRENT_SERIALS")"
    else
        update_pause_state_from_snapshots "$PREVIOUS_SERIALS" "$CURRENT_SERIALS" "$DEVICE_COUNT"
        AUTO_START="$(read_config_value auto_start)"
        AUTO_DISCOVER="$(read_config_value auto_discover)"
        PAUSE_ACTIVE="$(read_config_value pause_active)"
    fi
    resolve_open_cooldown_seconds

    save_current_serials "$CURRENT_SERIALS"

    # Contrato operativo:
    # - auto_start: habilita automatizacion del monitor.
    # - auto_discover: habilita reaccion a nuevas conexiones.
    # - pause_on_exit/pause_active: bloquea aperturas hasta evento valido o timeout.
    if [ -n "$DEVICE_SERIAL" ] && [ "$AUTO_START" = "true" ] && [ "$AUTO_DISCOVER" = "true" ] && [ "$PAUSE_ACTIVE" != "true" ]; then
        if [ "${MONITOR_TEST_MODE:-0}" = "1" ] || validate_menu_syntax; then
            if ! is_monitor_or_scrcpy_active "$DEVICE_SERIAL"; then
                if is_open_cooldown_active; then
                    log_block_reason_if_changed "$MONITOR_BLOCK_REASON"
                else
                    GEOMETRY="$(compute_terminal_geometry "$DEVICE_COUNT")"
                    if [ "${MONITOR_TEST_MODE:-0}" = "1" ]; then
                        echo "OPEN_TERMINAL:$GEOMETRY:$DEVICE_SERIAL"
                    else
                        log_message "[INFO] Opening monitor terminal for serial $DEVICE_SERIAL."
                        if open_menu_terminal "$GEOMETRY" "XYZ Monitor - $DEVICE_SERIAL"; then
                            touch_last_open_epoch
                            clear_block_reason_state
                        else
                            log_message "[WARNING] No compatible terminal emulator found. Popup launch skipped."
                        fi
                    fi
                    sleep 3
                fi
            else
                log_block_reason_if_changed "$MONITOR_BLOCK_REASON"
            fi
        else
            log_message "[CRITICAL] Syntax error in menu/config loader. Terminal launch blocked."
            sleep 30
        fi
    fi

    sleep 5
    if [ "${MONITOR_RUN_ONCE:-0}" = "1" ]; then
        break
    fi
done
# #xyz-rainbow
