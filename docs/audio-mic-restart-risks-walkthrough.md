# Audio/Mic Restart - Risks and Walkthrough

## Scope

This document describes the current behavior introduced for:

- `audio_target` (`host` / `device`)
- `active_recall` (`ON` / `OFF`)
- `microphone_bus` (`ON` / `OFF`)
- Main menu `RESTART` apply flow
- Virtual input bus name: `xyz-mic-input`

---

## Risks

### 1) Android microphone capture compatibility (Active Recall)

- `active_recall` is designed for direct Android microphone capture.
- Android microphone forwarding depends on installed `scrcpy` capabilities.
- The app detects support at runtime using `scrcpy --help`.
- If unsupported, launch continues without crashing and prints a warning.

Impact:
- `active_recall=ON` may not produce microphone forwarding on older builds.

Mitigation:
- Safe fallback with warning (`mic not supported by current scrcpy version`).

### 2) Linux audio stack dependency for microphone bus

- `microphone_bus` uses `pactl` (PulseAudio/PipeWire-compatible tooling).
- On systems without `pactl`, the app does not fail; it degrades gracefully.

Impact:
- `xyz-mic-input` may not be created when required tools are missing.

Mitigation:
- Installer notice when `pactl` is missing.
- Runtime warning and normal continuation.

### 3) OS-specific behavior

- Virtual bus auto-creation is currently Linux-only best effort.
- Windows path is supported as guided fallback: use a virtual cable tool and map it manually.
- Other non-Linux environments keep normal launch behavior and only show warnings.

Impact:
- Feature parity for `microphone_bus` is not identical across OSes.

Mitigation:
- Explicit warning path and no hard failure.

### 4) Restart race conditions

- `RESTART` stops/relaunches scrcpy for the remembered serial.
- Monitor and manual actions can overlap in edge timing windows.

Impact:
- Rare double-launch/restart timing anomalies may appear.

Mitigation:
- Existing anti-spam process guards in monitor.
- Saved `last_device_serial` + applied state tracking reduce ambiguity.

### 5) Legacy config migration expectations

- `sound` is still present for backward compatibility, but deprecated.
- Canonical behavior now comes from `audio_target`.

Impact:
- Manual edits that only touch `sound` may behave unexpectedly if inconsistent.

Mitigation:
- Normalizer keeps `sound` synchronized with `audio_target`.

---

## Walkthrough

### A) Change and apply audio target

1. Open `SETTINGS`.
2. Set `Audio target`:
   - `HOST`: plays audio on PC side.
   - `DEVICE`: keeps audio on Android (`--no-audio`).
3. Press `Apply`.
4. In main menu, press `RESTART` to apply to the running scrcpy flow.

Expected:
- `RESTART` is highlighted when pending audio/mic changes exist.
- After restart, pending state is cleared.

### B) Enable microphone forwarding (`active_recall`)

1. Open `SETTINGS`.
2. Toggle `Active Recall` to `ON`.
3. Press `Apply`.
4. Press `RESTART`.

Expected:
- If supported: launch includes mic flag (`--audio-source=mic`) and captures mic from Android.
- If unsupported: warning is shown, launch still succeeds.
- If `Audio target` was `DEVICE`, apply flow normalizes it to `HOST` for compatibility.

### C) Enable virtual microphone bus (`microphone_bus`)

1. Open `SETTINGS`.
2. Toggle `Microphone Bus` to `ON`.
3. Press `Apply`.
4. Press `RESTART`.

Expected:
- Linux with `pactl`: app attempts to create/reuse `xyz-mic-input` as remapped source from default sink monitor (without creating an extra dedicated virtual output sink).
- Windows: app warns and expects an external virtual cable setup (for example VB-CABLE), then manual routing to `xyz-mic-input`.
- Missing stack/tools: warning shown, no crash.

### D) Visual dirty-state guidance

- In `SETTINGS`, modified fields are highlighted in red.
- In main menu, `RESTART` highlights to indicate pending apply.

### E) Persisted apply state

After successful device launch/restart, these config fields are updated:

- `applied_audio_target`
- `applied_active_recall`
- `applied_microphone_bus`
- `last_device_serial`

This keeps pending-state detection stable between menu refreshes.

---

## Quick verification checklist

1. `Audio target=HOST`, `Active Recall=OFF`, `Microphone Bus=OFF`
2. `Audio target=DEVICE`, `Active Recall=OFF`, `Microphone Bus=OFF`
3. `Audio target=HOST`, `Active Recall=ON` (confirm support/fallback)
4. `Microphone Bus=ON` with and without `pactl` available
5. Confirm `RESTART` highlight behavior before/after apply
