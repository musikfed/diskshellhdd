from __future__ import annotations

import logging
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.scanner.quick_scan import scan


logger = logging.getLogger(__name__)
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


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
    }
    with _lock:
        _jobs[job_id] = job

    threading.Thread(
        target=_run_scan,
        args=(job_id, root),
        daemon=True,
        name=f"scan-{job_id[:8]}",
    ).start()
    return get_job(job_id)


def _run_scan(job_id: str, root: Path) -> None:
    with _lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = _now()

    def progress(data: dict[str, Any]) -> None:
        with _lock:
            job = _jobs[job_id]
            for key in ("scan_id", "current_path", "files", "directories", "bytes", "errors"):
                if key in data:
                    job[key] = data[key]

    try:
        scan_id = scan(root, progress_callback=progress)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background scan job %s failed", job_id)
        with _lock:
            job = _jobs[job_id]
            job["status"] = "failed"
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["finished_at"] = _now()
        return

    with _lock:
        job = _jobs[job_id]
        job["scan_id"] = scan_id
        job["status"] = "completed"
        job["finished_at"] = _now()


def get_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return deepcopy(job)
