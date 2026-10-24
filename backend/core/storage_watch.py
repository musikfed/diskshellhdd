from __future__ import annotations

import json
import threading
import time
from typing import Any

from backend.core.events import emit_event
from backend.core.logging_setup import log_error
from backend.files.service import list_roots


_lock = threading.Lock()
_started = False


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _roots_snapshot() -> dict[str, Any]:
    return list_roots()


def start_storage_event_watcher(interval_seconds: float = 3.0) -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def worker() -> None:
        roots_signature = ""
        while True:
            try:
                roots = _roots_snapshot()
                signature = _stable_json(roots)
                if signature != roots_signature:
                    had_previous_snapshot = bool(roots_signature)
                    roots_signature = signature
                    emit_event("storage.roots_changed", roots)
                    if had_previous_snapshot:
                        # A drive/root topology change is the useful trigger.
                        # Ask connected disk views to refresh once instead of
                        # running the expensive full PowerShell inventory here.
                        emit_event(
                            "storage.disks_changed",
                            {"refresh": True, "reason": "roots_changed"},
                        )
            except Exception as exc:  # noqa: BLE001
                log_error(
                    "storage.root_watcher_failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            time.sleep(max(1.0, float(interval_seconds)))

    threading.Thread(
        target=worker,
        daemon=True,
        name="storage-event-watcher",
    ).start()
