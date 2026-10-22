from __future__ import annotations

import re
import subprocess
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.core.database import connect, init_database
from backend.security.service import build_scan_command, choose_engine


_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_processes: dict[str, subprocess.Popen[str]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def start_security_scan(path: str, engine: str = "auto") -> dict[str, Any]:
    target = Path(path).resolve(strict=True)
    selected = choose_engine(engine)
    job_id = uuid.uuid4().hex
    job: dict[str, Any] = {
        "id": job_id,
        "type": "security_scan",
        "path": str(target),
        "engine": selected["id"],
        "engine_title": selected["title"],
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "threats": None,
        "output": "",
        "error": None,
        "cancel_requested": False,
    }
    with _lock:
        _jobs[job_id] = job

    threading.Thread(
        target=_run_scan,
        args=(job_id, target, selected),
        daemon=True,
        name=f"security-{job_id[:8]}",
    ).start()
    return get_security_job(job_id)


def _run_scan(job_id: str, target: Path, engine: dict[str, Any]) -> None:
    command = build_scan_command(engine, target)
    with _lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = _now()

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creation_flags,
    )
    with _lock:
        _processes[job_id] = process

    output = ""
    cancelled = False
    while True:
        try:
            stdout, _ = process.communicate(timeout=0.25)
            output = stdout or output
            break
        except subprocess.TimeoutExpired as exc:
            if exc.output:
                output = exc.output if isinstance(exc.output, str) else exc.output.decode("utf-8", "replace")
            with _lock:
                cancel_requested = bool(_jobs[job_id]["cancel_requested"])
            if cancel_requested:
                cancelled = True
                process.terminate()
                try:
                    stdout, _ = process.communicate(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, _ = process.communicate()
                if stdout:
                    output = stdout
                break

    with _lock:
        _processes.pop(job_id, None)

    exit_code = process.returncode
    if cancelled:
        status = "cancelled"
        threats = None
    else:
        threats = _count_threats(engine["id"], output)
        if engine["id"] == "clamav" and exit_code == 1:
            status = "threats_found"
        elif threats and threats > 0:
            status = "threats_found"
        elif exit_code == 0:
            status = "clean"
        else:
            status = "error"

    finished = _now()
    with _lock:
        job = _jobs[job_id]
        job["status"] = status
        job["finished_at"] = finished
        job["exit_code"] = exit_code
        job["threats"] = threats
        job["output"] = output[-20000:]
        if status == "error":
            job["error"] = f"Scanner exited with code {exit_code}"

    _persist_result(job_id)


def _count_threats(engine_id: str, output: str) -> int:
    if engine_id == "clamav":
        return sum(1 for line in output.splitlines() if line.rstrip().endswith("FOUND"))
    matches = re.findall(r"(?im)^\s*(?:threat|threats found)\s*[:=]", output)
    return len(matches)


def _persist_result(job_id: str) -> None:
    init_database()
    job = get_security_job(job_id)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO security_scan_results
                (path, engine, status, exit_code, threats, output, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["path"],
                job["engine"],
                job["status"],
                job["exit_code"],
                job["threats"],
                job["output"],
                job["started_at"],
                job["finished_at"] or _now(),
            ),
        )
        connection.commit()


def cancel_security_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] in {"clean", "threats_found", "error", "cancelled"}:
            return deepcopy(job)
        job["cancel_requested"] = True
        job["status"] = "cancelling"
        return deepcopy(job)


def get_security_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return deepcopy(job)


def recent_security_results(limit: int = 20) -> list[dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 100))
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, path, engine, status, exit_code, threats, started_at, completed_at
            FROM security_scan_results
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
