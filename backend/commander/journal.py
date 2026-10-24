from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from backend.core.database import connect, init_database


TERMINAL = {"completed", "completed_with_warnings", "failed", "cancelled"}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def create_job(job: dict[str, Any], transfers: list[dict[str, Any]]) -> None:
    init_database()
    now = now_iso()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO commander_jobs(
                id,status,operation,job_json,transfers_json,
                lease_owner,lease_expires_at,created_at,updated_at,finished_at
            ) VALUES(?,?,?,?,?,NULL,NULL,?,?,NULL)
            """,
            (
                str(job["id"]),
                str(job["status"]),
                str(job["operation"]),
                _dump(job),
                _dump(transfers),
                str(job.get("started_at") or now),
                now,
            ),
        )
        connection.commit()


def save_job(job: dict[str, Any], transfers: list[dict[str, Any]] | None = None) -> None:
    init_database()
    fields = [
        "status = ?",
        "operation = ?",
        "job_json = ?",
        "updated_at = ?",
        "finished_at = ?",
    ]
    values: list[Any] = [
        str(job.get("status") or "queued"),
        str(job.get("operation") or "copy"),
        _dump(job),
        now_iso(),
        job.get("finished_at"),
    ]
    if transfers is not None:
        fields.append("transfers_json = ?")
        values.append(_dump(transfers))
    values.append(str(job["id"]))
    with connect() as connection:
        connection.execute(
            f"UPDATE commander_jobs SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        connection.commit()


def load_job(job_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    init_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT job_json,transfers_json FROM commander_jobs WHERE id = ?",
            (str(job_id),),
        ).fetchone()
    if row is None:
        raise KeyError(job_id)
    return (
        json.loads(row["job_json"] or "{}"),
        json.loads(row["transfers_json"] or "[]"),
    )


def list_jobs(*, active_only: bool = False, limit: int = 50) -> list[dict[str, Any]]:
    init_database()
    bounded = max(1, min(200, int(limit)))
    params: list[Any] = []
    where = ""
    if active_only:
        placeholders = ",".join("?" for _ in TERMINAL)
        where = f"WHERE status NOT IN ({placeholders})"
        params.extend(sorted(TERMINAL))
    params.append(bounded)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT job_json FROM commander_jobs
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [json.loads(row["job_json"] or "{}") for row in rows]


def claim_job(job_id: str, owner: str, lease_seconds: float) -> bool:
    now = time.time()
    expires = now + float(lease_seconds)
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT status,lease_owner,lease_expires_at
            FROM commander_jobs
            WHERE id = ?
            """,
            (str(job_id),),
        ).fetchone()
        if row is None or str(row["status"]) in TERMINAL:
            connection.rollback()
            return False
        current_owner = row["lease_owner"]
        current_expiry = float(row["lease_expires_at"] or 0)
        if current_owner and current_owner != owner and current_expiry > now:
            connection.rollback()
            return False
        connection.execute(
            """
            UPDATE commander_jobs
            SET lease_owner=?,lease_expires_at=?,updated_at=?
            WHERE id=?
            """,
            (owner, expires, now_iso(), str(job_id)),
        )
        connection.commit()
    return True


def renew_lease(job_id: str, owner: str, lease_seconds: float) -> bool:
    expires = time.time() + float(lease_seconds)
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE commander_jobs
            SET lease_expires_at=?,updated_at=?
            WHERE id=? AND lease_owner=?
            """,
            (expires, now_iso(), str(job_id), str(owner)),
        )
        connection.commit()
    return cursor.rowcount == 1


def release_lease(job_id: str, owner: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE commander_jobs
            SET lease_owner=NULL,lease_expires_at=NULL,updated_at=?
            WHERE id=? AND lease_owner=?
            """,
            (now_iso(), str(job_id), str(owner)),
        )
        connection.commit()
