import json
import os
import tempfile

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "../config/config.json")

DEFAULT_CONFIG = {
    "command_alias": "xyz-scrcpy",
    "audio_target": "host",
    "sound": "output",
    "active_recall": False,
    "microphone_bus": False,
    "applied_audio_target": "host",
    "applied_active_recall": False,
    "applied_microphone_bus": False,
    "last_device_serial": "",
    "auto_start": True,
    "auto_discover": True,
    "open_cooldown_seconds": 30,
    "resolution": "1080p",
    "exit_pause_minutes": 1440,
    "pause_on_exit": False,
    "pause_active": False,
    "pause_until_epoch": 0,
    "pause_wait_reconnect": False,
    "pause_seen_disconnect": False,
}


def _normalize_config(raw_cfg):
    raw_cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
    cfg = dict(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        if key in raw_cfg:
            cfg[key] = raw_cfg[key]

    # Compatibilidad legacy
    if "audio_target" not in raw_cfg and "sound" in raw_cfg:
        cfg["audio_target"] = "device" if str(raw_cfg.get("sound", "output")) == "off" else "host"
    if "sound" not in raw_cfg and "default_audio" in raw_cfg:
        cfg["sound"] = raw_cfg.get("default_audio", cfg["sound"])
    if "auto_start" not in raw_cfg and "autostart" in raw_cfg:
        cfg["auto_start"] = bool(raw_cfg.get("autostart"))

    cfg["auto_start"] = bool(cfg.get("auto_start", True))
    cfg["auto_discover"] = bool(cfg.get("auto_discover", True))
    cfg["active_recall"] = bool(cfg.get("active_recall", False))
    cfg["microphone_bus"] = bool(cfg.get("microphone_bus", False))
    cfg["applied_active_recall"] = bool(cfg.get("applied_active_recall", False))
    cfg["applied_microphone_bus"] = bool(cfg.get("applied_microphone_bus", False))
    cfg["pause_on_exit"] = bool(cfg.get("pause_on_exit", False))
    cfg["pause_active"] = bool(cfg.get("pause_active", False))
    cfg["pause_wait_reconnect"] = bool(cfg.get("pause_wait_reconnect", False))
    cfg["pause_seen_disconnect"] = bool(cfg.get("pause_seen_disconnect", False))
    if "exit_pause_minutes" in raw_cfg:
        cfg["exit_pause_minutes"] = int(raw_cfg.get("exit_pause_minutes", 1440) or 1440)
    elif "exit_pause_seconds" in raw_cfg:
        legacy_seconds = int(raw_cfg.get("exit_pause_seconds", 86400) or 86400)
        cfg["exit_pause_minutes"] = max(1, legacy_seconds // 60)
    else:
        cfg["exit_pause_minutes"] = int(cfg.get("exit_pause_minutes", 1440) or 1440)
    cfg["exit_pause_minutes"] = max(1, cfg["exit_pause_minutes"])
    try:
        cooldown = int(cfg.get("open_cooldown_seconds", DEFAULT_CONFIG["open_cooldown_seconds"]) or DEFAULT_CONFIG["open_cooldown_seconds"])
    except (TypeError, ValueError):
        cooldown = DEFAULT_CONFIG["open_cooldown_seconds"]
    cfg["open_cooldown_seconds"] = max(0, min(cooldown, 600))
    cfg["pause_until_epoch"] = int(cfg.get("pause_until_epoch", 0) or 0)
    cfg["command_alias"] = str(cfg.get("command_alias", "xyz-scrcpy"))
    audio_target = str(cfg.get("audio_target", "host")).strip().lower()
    if audio_target not in {"host", "device"}:
        audio_target = "host"
    cfg["audio_target"] = audio_target
    applied_audio_target = str(cfg.get("applied_audio_target", audio_target)).strip().lower()
    if applied_audio_target not in {"host", "device"}:
        applied_audio_target = audio_target
    cfg["applied_audio_target"] = applied_audio_target

    cfg["sound"] = str(cfg.get("sound", "output")).strip().lower()
    if cfg["sound"] not in {"output", "off"}:
        cfg["sound"] = "output"
    # Keep legacy key in sync during transition.
    cfg["sound"] = "off" if cfg["audio_target"] == "device" else "output"
    cfg["last_device_serial"] = str(cfg.get("last_device_serial", "") or "")
    cfg["resolution"] = str(cfg.get("resolution", "1080p"))
    return cfg


def load_config():
    raw_cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw_cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            raw_cfg = {}
    cfg = _normalize_config(raw_cfg)
    save_config(cfg)
    return cfg


def save_config(cfg):
    clean_cfg = _normalize_config(cfg if isinstance(cfg, dict) else {})
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", delete=False, encoding="utf-8", dir=os.path.dirname(CONFIG_PATH)
    ) as tmp:
        json.dump(clean_cfg, tmp, indent=2)
        tmp.write("\n")
        temp_path = tmp.name
    os.replace(temp_path, CONFIG_PATH)
