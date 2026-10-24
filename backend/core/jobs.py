from __future__ import annotations

import logging
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.core.events import emit_event
from backend.scanner.quick_scan import ScanCancelled, scan


logger = logging.getLogger(__name__)
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_cancel_events: dict[str, threading.Event] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def start_scan_job(path: str) -> dict[str, Any]:
    root = Path(path).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)

    job_id = uuid.uuid4().hex
    job: dict[str, Any] = {
        "id": job_id,
        "type": "quick_scan",
        "status": "queued",
        "root": str(root),
        "current_path": str(root),
        "files": 0,
        "directories": 0,
        "bytes": 0,
        "errors": 0,
        "scan_id": None,
        "started_at": None,
        "finished_at": None,
        "error": None,
        "cancel_requested": False,
    }
    event = threading.Event()
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = event

    emit_event("scan.started", {"job_id": job_id, "root": str(root)})
    threading.Thread(
        target=_run_scan,
        args=(job_id, root, event),
        daemon=True,
        name=f"scan-{job_id[:8]}",
    ).start()
    return get_job(job_id)


def _run_scan(job_id: str, root: Path, cancel_event: threading.Event) -> None:
    with _lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = _now()

    def progress(data: dict[str, Any]) -> None:
        with _lock:
            job = _jobs[job_id]
            for key in ("scan_id", "current_path", "files", "directories", "bytes", "errors"):
                if key in data:
                    job[key] = data[key]
        emit_event(
            "scan.progress",
            {
                "job_id": job_id,
                "scan_id": data.get("scan_id"),
                "current_path": data.get("current_path"),
                "files": data.get("files"),
                "directories": data.get("directories"),
                "bytes": data.get("bytes"),
                "errors": data.get("errors"),
            },
        )

    try:
        scan_id = scan(
            root,
            progress_callback=progress,
            cancel_callback=cancel_event.is_set,
        )
    except ScanCancelled:
        with _lock:
            job = _jobs[job_id]
            job["status"] = "cancelled"
            job["finished_at"] = _now()
        emit_event("scan.cancelled", {"job_id": job_id})
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background scan job %s failed", job_id)
        with _lock:
            job = _jobs[job_id]
            job["status"] = "failed"
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["finished_at"] = _now()
        emit_event(
            "scan.failed",
            {"job_id": job_id, "error": f"{type(exc).__name__}: {exc}"},
        )
        return
    finally:
        with _lock:
            _cancel_events.pop(job_id, None)

    with _lock:
        job = _jobs[job_id]
        job["scan_id"] = scan_id
        job["status"] = "completed"
        job["finished_at"] = _now()
    emit_event("scan.completed", {"job_id": job_id, "scan_id": scan_id})


def cancel_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] in {"completed", "failed", "cancelled"}:
            return deepcopy(job)
        event = _cancel_events.get(job_id)
        if event is not None:
            event.set()
        job["cancel_requested"] = True
        job["status"] = "cancelling"
        return deepcopy(job)


def get_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return deepcopy(job)
