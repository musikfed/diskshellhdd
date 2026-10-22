from __future__ import annotations

import logging
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from backend.storage_brain.executor import (
    PlanExecutionBlocked,
    PlanExecutionCancelled,
    apply_plan,
)


logger = logging.getLogger(__name__)
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_cancel_events: dict[str, threading.Event] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def start_plan_job(plan_id: int, confirmation: str, verify: str = "size") -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    event = threading.Event()
    job: dict[str, Any] = {
        "id": job_id,
        "type": "placement_apply",
        "plan_id": int(plan_id),
        "status": "queued",
        "verify": verify,
        "completed": 0,
        "failed": 0,
        "copied": 0,
        "moved": 0,
        "total": 0,
        "total_bytes": 0,
        "processed_bytes": 0,
        "progress_percent": None,
        "current": None,
        "started_at": None,
        "finished_at": None,
        "error": None,
        "result": None,
        "cancel_requested": False,
    }
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = event

    threading.Thread(
        target=_run,
        args=(job_id, int(plan_id), confirmation, verify, event),
        daemon=True,
        name=f"placement-{job_id[:8]}",
    ).start()
    return get_plan_job(job_id)


def _run(
    job_id: str,
    plan_id: int,
    confirmation: str,
    verify: str,
    cancel_event: threading.Event,
) -> None:
    with _lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = _now()

    def progress(data: dict[str, Any]) -> None:
        with _lock:
            job = _jobs[job_id]
            for key in (
                "completed",
                "failed",
                "copied",
                "moved",
                "total",
                "total_bytes",
                "processed_bytes",
                "progress_percent",
                "current",
            ):
                if key in data:
                    job[key] = data[key]

    try:
        result = apply_plan(
            plan_id,
            confirmation,
            verify,
            cancel_callback=cancel_event.is_set,
            progress_callback=progress,
        )
    except PlanExecutionCancelled:
        with _lock:
            job = _jobs[job_id]
            job["status"] = "cancelled"
            job["finished_at"] = _now()
        return
    except PlanExecutionBlocked as exc:
        with _lock:
            job = _jobs[job_id]
            job["status"] = "blocked"
            job["error"] = str(exc)
            job["finished_at"] = _now()
        return
    except Exception as exc:  # noqa: BLE001
        logger.exception("Placement job %s failed", job_id)
        with _lock:
            job = _jobs[job_id]
            job["status"] = "failed"
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["finished_at"] = _now()
        return
    finally:
        with _lock:
            _cancel_events.pop(job_id, None)

    with _lock:
        job = _jobs[job_id]
        job["status"] = result["status"]
        job["result"] = result
        job["finished_at"] = _now()


def cancel_plan_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] in {"completed", "failed", "blocked", "cancelled", "partial"}:
            return deepcopy(job)
        event = _cancel_events.get(job_id)
        if event is not None:
            event.set()
        job["cancel_requested"] = True
        job["status"] = "cancelling"
        return deepcopy(job)


def get_plan_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return deepcopy(job)
