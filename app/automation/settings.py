"""Persistent settings for meeting automation.

Unlike the core app (which keeps API keys in memory only), the automation runs
unattended on a 24/7 server and must remember its credentials across restarts.
So these live in a JSON file on disk: DATA_DIR/automation.json.

SECURITY NOTE: this file contains the Weeek token and cloud OAuth tokens in
plain text. Keep the data directory private (chmod 700 on the server). The file
is created with 0600 permissions where the OS supports it.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any

from .. import config

_PATH = config.DATA_DIR / "automation.json"
_LOCK = threading.Lock()

# Default shape. Anything missing from the on-disk file falls back to these.
_DEFAULTS: dict[str, Any] = {
    "enabled": False,                 # master switch for the scheduler
    # --- Weeek task tracker ---
    "weeek_token": "",
    "weeek_project_id": None,         # optional: limit polling to one project
    # --- where to put finished recordings ---
    "cloud": "local",                 # "local" | "gdrive" | "yandex_disk"
    "yandex_disk": {"token": "", "folder": "disk:/Телемост-записи"},
    "gdrive": {"client_config": "", "token": "", "folder_id": ""},
    "local_dir": "",                  # empty -> DATA_DIR/recordings
    # --- scheduler / bot behaviour ---
    "poll_interval_sec": 120,         # how often to re-read Weeek
    "lookahead_min": 2,               # join the meeting this many min early
    "max_meeting_min": 240,           # hard cap on a single recording
    "bot_join_name": "Протокол-бот",  # display name shown in Telemost
    "headless": True,
    # --- after recording ---
    "analyze_provider": "auto",       # which LLM builds the protocol
    "post_back_to_weeek": True,       # attach protocol link as a task comment
}


def _atomic_write(data: dict[str, Any]) -> None:
    tmp = _PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.replace(tmp, _PATH)
    finally:
        try:
            os.chmod(_PATH, 0o600)
        except OSError:
            pass  # Windows / unsupported FS — best effort only


def load() -> dict[str, Any]:
    """Return the full settings dict (defaults merged with the on-disk file)."""
    with _LOCK:
        data = dict(_DEFAULTS)
        if _PATH.exists():
            try:
                stored = json.loads(_PATH.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    data.update(stored)
            except (ValueError, OSError):
                pass  # corrupt file -> fall back to defaults
        return data


def save(values: dict[str, Any]) -> dict[str, Any]:
    """Merge `values` into the stored settings and persist. Returns new state."""
    with _LOCK:
        data = dict(_DEFAULTS)
        if _PATH.exists():
            try:
                stored = json.loads(_PATH.read_text(encoding="utf-8"))
                if isinstance(stored, dict):
                    data.update(stored)
            except (ValueError, OSError):
                pass
        data.update(values)
        _atomic_write(data)
        return data


def get(key: str, default: Any = None) -> Any:
    return load().get(key, default)


def redacted() -> dict[str, Any]:
    """Settings safe to send to the UI — secrets replaced with a presence flag."""
    data = load()
    out = dict(data)
    out["weeek_token"] = bool(data.get("weeek_token"))
    yd = dict(data.get("yandex_disk") or {})
    yd["token"] = bool(yd.get("token"))
    out["yandex_disk"] = yd
    gd = dict(data.get("gdrive") or {})
    gd["token"] = bool(gd.get("token"))
    gd["client_config"] = bool(gd.get("client_config"))
    out["gdrive"] = gd
    return out
