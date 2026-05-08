#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="${XYZ_CHECK_LOG_FILE:-$REPO_DIR/config/check.log}"
TIMEOUT_SECONDS="${XYZ_CHECK_TIMEOUT_SECONDS:-90}"
CHECK_MODE="${XYZ_CHECK_MODE:-full}"
HOME_DIR="${HOME:-}"
CHECK_START_EPOCH=0

mkdir -p "$REPO_DIR/config"

sanitize_text() {
    local input="$1"
    local out="$input"
    if [ -n "$HOME_DIR" ]; then
        out="${out//${HOME_DIR}/~}"
    fi
    out="${out//${REPO_DIR}/.}"
    printf '%s' "$out"
}

append_sanitized_file() {
    local file="$1"
    if [ ! -f "$file" ]; then
        return
    fi
    while IFS= read -r line || [ -n "$line" ]; do
        sanitize_text "$line" >> "$LOG_FILE"
        printf '\n' >> "$LOG_FILE"
    done < "$file"
}

log() {
    local msg="$1"
    local sanitized
    sanitized="$(sanitize_text "$msg")"
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$sanitized" | tee -a "$LOG_FILE"
}

detect_os_info() {
    local kernel os_pretty
    kernel="$(uname -srmo 2>/dev/null || uname -a)"
    os_pretty=""
    if [ -f /etc/os-release ]; then
        os_pretty="$(. /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-}")"
    fi
    if [ -z "$os_pretty" ]; then
        os_pretty="$(uname -s)"
    fi
    log "System info: os=${os_pretty}; kernel=${kernel}"
}

run_step() {
    local cmd="$1"
    local tmp_out
    tmp_out="$(mktemp)"
    if ! timeout "$TIMEOUT_SECONDS" bash -lc "$cmd" > "$tmp_out" 2>&1; then
        append_sanitized_file "$tmp_out"
        rm -f "$tmp_out"
        return 1
    fi
    append_sanitized_file "$tmp_out"
    rm -f "$tmp_out"
    return 0
}

run_checks() {
    : > "$LOG_FILE"
    CHECK_START_EPOCH="$(date +%s)"
    log "Starting automated checks (mode: $CHECK_MODE)."
    detect_os_info
    if [ "${XYZ_TEST_MODE:-0}" = "1" ]; then
        case "${XYZ_TEST_SCENARIO:-pass}" in
            pass)
                log "Test mode: checks passed."
                return 0
                ;;
            fail)
                log "Test mode: checks failed."
                return 1
                ;;
            repair-pass)
                if [ "${XYZ_TEST_REPAIR_DONE:-0}" = "1" ]; then
                    log "Test mode: checks passed after repair."
                    return 0
                fi
                log "Test mode: initial checks failed."
                return 1
                ;;
        esac
    fi

    run_step "cd \"$REPO_DIR\" && python3 -m py_compile install_xyz.py bin/menu.py bin/config_loader.py" || return 1
    run_step "cd \"$REPO_DIR\" && bash -n bin/monitor.sh" || return 1
    run_step "cd \"$REPO_DIR\" && bash -n bin/check_and_repair.sh" || return 1
    run_step "cd \"$REPO_DIR\" && bash -n bin/launch_with_checks.sh" || return 1
    if [ "$CHECK_MODE" = "full" ]; then
        run_step "cd \"$REPO_DIR\" && python3 -m unittest discover -s tests -p \"test_*.py\"" || return 1
    fi
    local end_epoch elapsed
    end_epoch="$(date +%s)"
    elapsed=$((end_epoch - CHECK_START_EPOCH))
    log "Timing: start_epoch=${CHECK_START_EPOCH}; end_epoch=${end_epoch}; elapsed_seconds=${elapsed}"
    log "All automated checks passed."
    return 0
}

run_repair() {
    local repair_start repair_end repair_elapsed repair_exit
    repair_start="$(date +%s)"
    log "Checks failed, running repair workflow."
    log "Auto-repair: started."
    if [ "${XYZ_TEST_MODE:-0}" = "1" ]; then
        export XYZ_TEST_REPAIR_DONE=1
        log "Test mode: simulated repair completed."
        repair_end="$(date +%s)"
        repair_elapsed=$((repair_end - repair_start))
        log "Auto-repair: finished (simulated)."
        log "Auto-repair timing: start_epoch=${repair_start}; end_epoch=${repair_end}; elapsed_seconds=${repair_elapsed}"
        return 0
    fi
    if run_step "cd \"$REPO_DIR\" && bash ./repair_xyz.sh"; then
        repair_exit=0
    else
        repair_exit=$?
    fi
    repair_end="$(date +%s)"
    repair_elapsed=$((repair_end - repair_start))
    log "Auto-repair: finished."
    log "Auto-repair result: exit_code=${repair_exit}"
    log "Auto-repair timing: start_epoch=${repair_start}; end_epoch=${repair_end}; elapsed_seconds=${repair_elapsed}"
    if [ "$repair_exit" -ne 0 ]; then
        log "Auto-repair warning: workflow reported non-zero exit code, continuing with re-check by contract."
    fi
}

if run_checks; then
    echo "PASS"
    exit 0
fi

run_repair
log "Post-repair: re-running checks."
if run_checks; then
    echo "PASS_AFTER_REPAIR"
    exit 0
fi

log "Checks are still failing after repair."
if [ "$CHECK_START_EPOCH" -gt 0 ]; then
    fail_end_epoch="$(date +%s)"
    fail_elapsed=$((fail_end_epoch - CHECK_START_EPOCH))
    log "Timing: start_epoch=${CHECK_START_EPOCH}; end_epoch=${fail_end_epoch}; elapsed_seconds=${fail_elapsed}"
fi
log "Please report this issue at: https://github.com/xyz-rainbow/xyz-scrcpy/issues"
log "GitHub issue creation requires login; you can also email check.log to rainbow@rainbowtechnology.xyz"
echo "FAIL_OPEN"
exit 0
