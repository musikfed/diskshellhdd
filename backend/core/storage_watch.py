from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from backend.core.events import emit_event
from backend.core.logging_setup import log_error
from backend.files.service import list_roots
from backend.services.storage.windows_disks import list_windows_disks


_lock = threading.Lock()
_started = False


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _roots_snapshot() -> dict[str, Any]:
    return list_roots()


def _disks_snapshot() -> dict[str, Any] | None:
    if os.name != "nt":
        return None
    return {"disks": list_windows_disks()}


def start_storage_event_watcher(interval_seconds: float = 3.0) -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def worker() -> None:
        roots_signature = ""
        disks_signature = ""
        while True:
            try:
                roots = _roots_snapshot()
                signature = _stable_json(roots)
                if signature != roots_signature:
                    roots_signature = signature
                    emit_event("storage.roots_changed", roots)
            except Exception as exc:  # noqa: BLE001
                log_error(
                    "storage.root_watcher_failed",
                    error=f"{type(exc).__name__}: {exc}",
                )

            try:
                disks = _disks_snapshot()
                if disks is not None:
                    signature = _stable_json(disks)
                    if signature != disks_signature:
                        disks_signature = signature
                        emit_event("storage.disks_changed", disks)
            except Exception as exc:  # noqa: BLE001
                log_error(
                    "storage.disk_watcher_failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            time.sleep(max(1.0, float(interval_seconds)))

    threading.Thread(
        target=worker,
        daemon=True,
        name="storage-event-watcher",
    ).start()
