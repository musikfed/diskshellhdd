from __future__ import annotations

import json
import statistics
import threading
import time
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from backend.core.database import connect, init_database
from backend.services.storage.windows_disks import list_windows_disks
from backend.services.storage.windows_privileges import require_process_elevated


MIB = 1024 * 1024

PROFILES = {
    "quick": {"cells": 192, "sample_bytes": 2 * MIB, "full": False},
    "standard": {"cells": 256, "sample_bytes": 16 * MIB, "full": False},
    "full": {"cells": 256, "sample_bytes": None, "full": True},
}

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_cancel_events: dict[str, threading.Event] = {}


class DiagnosticCancelled(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _disk_identity(disk: dict[str, Any]) -> str:
    return "|".join(
        [
            str(disk.get("unique_id") or ""),
            str(disk.get("serial_number") or ""),
            str(disk.get("size") or 0),
        ]
    )


def _disk_by_number(disk_number: int) -> dict[str, Any]:
    for disk in list_windows_disks():
        if int(disk["number"]) == int(disk_number):
            return disk
    raise ValueError("Disk not found")


def _check_cancel(event: threading.Event) -> None:
    if event.is_set():
        raise DiagnosticCancelled("Surface diagnostic cancelled by operator")


def _open_raw_device(path: str):
    import win32con
    import win32file

    return win32file.CreateFile(
        path,
        win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
        None,
        win32con.OPEN_EXISTING,
        0,
        None,
    )


def _read_span(
    handle,
    offset: int,
    length: int,
    event: threading.Event,
    chunk_size: int = 8 * MIB,
) -> int:
    import win32file

    win32file.SetFilePointer(handle, int(offset), win32file.FILE_BEGIN)
    remaining = int(length)
    total = 0
    while remaining > 0:
        _check_cancel(event)
        request = min(chunk_size, remaining)
        _, data = win32file.ReadFile(handle, request, None)
        if not data:
            raise OSError("Short raw read")
        count = len(data)
        total += count
        remaining -= count
    return total


def _make_cells(disk_size: int, count: int) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    for index in range(count):
        start = disk_size * index // count
        end = disk_size * (index + 1) // count
        cells.append(
            {
                "index": index,
                "start": start,
                "end": end,
                "region_bytes": max(0, end - start),
                "sample_offset": None,
                "sample_bytes": 0,
                "status": "pending",
                "mib_s": None,
                "latency_ms": None,
                "error": None,
            }
        )
    return cells


def _persist(job: dict[str, Any]) -> None:
    summary = {
        key: job.get(key)
        for key in (
            "friendly_name",
            "serial_number",
            "bus_type",
            "health_status",
            "reliability",
            "progress_percent",
            "completed_cells",
            "total_cells",
            "warn_cells",
            "slow_cells",
            "read_errors",
            "median_mib_s",
            "rating",
            "note",
        )
    }
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO diagnostic_runs (
                id, disk_number, disk_identity, mode, status, started_at,
                completed_at, rating, total_bytes, sampled_bytes, read_errors,
                slow_cells, cells_json, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                completed_at=excluded.completed_at,
                rating=excluded.rating,
                sampled_bytes=excluded.sampled_bytes,
                read_errors=excluded.read_errors,
                slow_cells=excluded.slow_cells,
                cells_json=excluded.cells_json,
                summary_json=excluded.summary_json
            """,
            (
                job["id"],
                job["disk_number"],
                job["disk_identity"],
                job["mode"],
                job["status"],
                job["started_at"],
                job.get("finished_at"),
                job.get("rating"),
                job["total_bytes"],
                job["sampled_bytes"],
                job["read_errors"],
                job["slow_cells"],
                json.dumps(job["cells"], ensure_ascii=False),
                json.dumps(summary, ensure_ascii=False),
            ),
        )
        connection.commit()


def _classify_cells(cells: list[dict[str, Any]]) -> tuple[int, int, float | None]:
    speeds = [
        float(cell["mib_s"])
        for cell in cells
        if cell["error"] is None and cell["mib_s"] is not None
    ]
    if not speeds:
        return 0, 0, None

    median = statistics.median(speeds)
    slow_cutoff = max(5.0, median * 0.25)
    warn_cutoff = max(15.0, median * 0.50)
    warn = 0
    slow = 0
    for cell in cells:
        if cell["error"] is not None:
            cell["status"] = "bad"
            continue
        speed = float(cell["mib_s"] or 0.0)
        if speed < slow_cutoff:
            cell["status"] = "slow"
            slow += 1
        elif speed < warn_cutoff:
            cell["status"] = "warn"
            warn += 1
        else:
            cell["status"] = "good"
    return warn, slow, float(median)


def _rating(job: dict[str, Any]) -> str:
    health = str(job.get("health_status") or "").casefold()
    reliability = job.get("reliability") or {}
    lifetime_errors = int(reliability.get("read_errors_total") or 0) + int(
        reliability.get("write_errors_total") or 0
    )
    smart_available = any(value is not None for value in reliability.values())

    if job["read_errors"] > 0 or "unhealthy" in health:
        return "Bad"
    if "warning" in health or job["slow_cells"] > 0 or lifetime_errors > 0:
        return "Warning"
    if smart_available and job["warn_cells"] == 0 and "healthy" in health:
        return "Excellent"
    return "Good"


def start_surface_job(disk_number: int, mode: str = "quick") -> dict[str, Any]:
    init_database()
    require_process_elevated()

    profile = PROFILES.get(str(mode).casefold())
    if profile is None:
        raise ValueError("mode must be quick, standard, or full")

    disk = _disk_by_number(disk_number)
    if disk.get("protected") and profile["full"]:
        raise ValueError(
            "Full surface read is disabled for protected system/boot/application disks"
        )

    with _lock:
        for existing in _jobs.values():
            if (
                int(existing["disk_number"]) == int(disk_number)
                and existing["status"] in {"queued", "running", "cancelling"}
            ):
                raise ValueError("A diagnostic job is already running for this disk")

    job_id = uuid.uuid4().hex
    cells = _make_cells(int(disk["size"]), int(profile["cells"]))
    event = threading.Event()
    job: dict[str, Any] = {
        "id": job_id,
        "type": "surface_diagnostic",
        "disk_number": int(disk_number),
        "disk_identity": _disk_identity(disk),
        "friendly_name": disk.get("friendly_name"),
        "serial_number": disk.get("serial_number"),
        "bus_type": disk.get("bus_type"),
        "health_status": disk.get("health_status"),
        "reliability": disk.get("reliability") or {},
        "mode": str(mode).casefold(),
        "status": "queued",
        "started_at": _now(),
        "finished_at": None,
        "total_bytes": int(disk["size"]),
        "sampled_bytes": 0,
        "completed_cells": 0,
        "total_cells": len(cells),
        "progress_percent": 0.0,
        "warn_cells": 0,
        "slow_cells": 0,
        "read_errors": 0,
        "median_mib_s": None,
        "rating": None,
        "current_cell": None,
        "cancel_requested": False,
        "cells": cells,
        "note": (
            "Read-only diagnostic. Sampling modes can find obvious read failures and "
            "slow regions but cannot prove the entire surface is healthy."
        ),
    }

    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = event
    _persist(job)

    threading.Thread(
        target=_run_surface_job,
        args=(job_id, disk, profile, event),
        daemon=True,
        name=f"surface-{job_id[:8]}",
    ).start()
    return get_surface_job(job_id)


def _run_surface_job(
    job_id: str,
    disk: dict[str, Any],
    profile: dict[str, Any],
    event: threading.Event,
) -> None:
    with _lock:
        job = _jobs[job_id]
        job["status"] = "running"

    handle = None
    try:
        handle = _open_raw_device(str(disk["device_id"]))
        sector = max(512, int(disk.get("logical_sector_size") or 512))
        cells = _jobs[job_id]["cells"]

        for cell in cells:
            _check_cancel(event)
            region = int(cell["region_bytes"])
            if region <= 0:
                cell["status"] = "good"
                continue

            if profile["full"]:
                sample_offset = int(cell["start"])
                sample_bytes = region
            else:
                wanted = min(int(profile["sample_bytes"]), region)
                wanted -= wanted % sector
                sample_bytes = max(sector, wanted)
                center = int(cell["start"]) + max(0, (region - sample_bytes) // 2)
                sample_offset = center - (center % sector)
                if sample_offset + sample_bytes > int(cell["end"]):
                    sample_offset = max(
                        int(cell["start"]),
                        int(cell["end"]) - sample_bytes,
                    )
                    sample_offset -= sample_offset % sector

            with _lock:
                job = _jobs[job_id]
                job["current_cell"] = int(cell["index"])
                cell["status"] = "reading"
                cell["sample_offset"] = sample_offset
                cell["sample_bytes"] = sample_bytes

            started = time.perf_counter()
            try:
                read_bytes = _read_span(
                    handle,
                    sample_offset,
                    sample_bytes,
                    event,
                )
                elapsed = max(time.perf_counter() - started, 1e-9)
                mib_s = (read_bytes / MIB) / elapsed
                with _lock:
                    job = _jobs[job_id]
                    cell["mib_s"] = round(mib_s, 2)
                    cell["latency_ms"] = round(elapsed * 1000.0, 2)
                    cell["status"] = "good"
                    job["sampled_bytes"] += read_bytes
            except DiagnosticCancelled:
                raise
            except OSError as exc:
                with _lock:
                    job = _jobs[job_id]
                    cell["status"] = "bad"
                    cell["error"] = str(exc)
                    job["read_errors"] += 1

            with _lock:
                job = _jobs[job_id]
                job["completed_cells"] += 1
                job["progress_percent"] = round(
                    job["completed_cells"] * 100.0 / job["total_cells"],
                    2,
                )
                snapshot = deepcopy(job)
            if int(cell["index"]) % 8 == 0:
                _persist(snapshot)

        with _lock:
            job = _jobs[job_id]
            warn, slow, median = _classify_cells(job["cells"])
            job["warn_cells"] = warn
            job["slow_cells"] = slow
            job["median_mib_s"] = round(median, 2) if median is not None else None
            job["rating"] = _rating(job)
            job["status"] = "completed"
            job["progress_percent"] = 100.0
            job["current_cell"] = None
            job["finished_at"] = _now()
            snapshot = deepcopy(job)
        _persist(snapshot)

    except DiagnosticCancelled:
        with _lock:
            job = _jobs[job_id]
            job["status"] = "cancelled"
            job["finished_at"] = _now()
            job["current_cell"] = None
            snapshot = deepcopy(job)
        _persist(snapshot)
    except Exception as exc:  # noqa: BLE001
        with _lock:
            job = _jobs[job_id]
            job["status"] = "failed"
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["finished_at"] = _now()
            job["current_cell"] = None
            snapshot = deepcopy(job)
        _persist(snapshot)
    finally:
        if handle is not None:
            handle.Close()
        with _lock:
            _cancel_events.pop(job_id, None)


def get_surface_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return deepcopy(job)


def cancel_surface_job(job_id: str) -> dict[str, Any]:
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


def recent_diagnostics(limit: int = 10) -> list[dict[str, Any]]:
    init_database()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM diagnostic_runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (max(1, min(50, int(limit))),),
        ).fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["summary"] = json.loads(item.pop("summary_json") or "{}")
        item["cells"] = json.loads(item.pop("cells_json") or "[]")
        result.append(item)
    return result
