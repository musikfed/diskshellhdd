from __future__ import annotations

import threading

from backend.config import settings


_lock = threading.Lock()
_runtime_enabled = False


def file_write_state() -> dict:
    with _lock:
        runtime_enabled = bool(_runtime_enabled)
    global_override = bool(settings.allow_file_writes)
    return {
        "allowed": bool(global_override or runtime_enabled),
        "runtime_enabled": runtime_enabled,
        "global_override": global_override,
        "mode": "manual_until_restart" if runtime_enabled and not global_override else "environment",
    }


def file_writes_allowed() -> bool:
    return bool(file_write_state()["allowed"])


def set_runtime_file_writes(enabled: bool) -> dict:
    global _runtime_enabled
    with _lock:
        _runtime_enabled = bool(enabled)
    return file_write_state()
