from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from backend.core.database import connect, init_database


TERMINAL_STATES = {"completed", "completed_with_warnings", "failed", "cancelled"}
JOB_FIELDS = {
    "status",
    "target_root",
    "current_item_index",
    "current_path",
    "bytes",
    "total_bytes",
    "files",
    "total_files",
    "skipped",
    "skipped_bytes",
    "manifest_files",
    "manifest_directories",
    "warnings_json",
    "error",
    "progress_percent",
    "average_mib_s",
    "wait_cycles",
    "auto_resumes",
    "waiting_since",
    "lease_owner",
    "lease_expires_at",
    "updated_at",
    "finished_at",
}
ITEM_FIELDS = {
    "status",
    "confirmed_offset",
    "error",
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def create_job(job: dict[str, Any]) -> None:
    init_database()
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO streamcopy_jobs (
                id, status, source_path, destination_path,
                source_endpoint_json, destination_endpoint_json, profile_json,
                verify_mode, delete_source_after_verify,
                target_root, current_item_index, current_path,
                bytes, total_bytes, files, total_files, skipped, skipped_bytes,
                manifest_files, manifest_directories, warnings_json, error,
                progress_percent, average_mib_s, wait_cycles, auto_resumes,
                waiting_since, lease_owner, lease_expires_at,
                created_at, updated_at, finished_at
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?
            )
            """,
            (
                job["id"],
                job["status"],
                job["source_path"],
                job["destination_path"],
                _json(job.get("source_endpoint") or {}),
                _json(job.get("destination_endpoint") or {}),
                _json(job.get("profile") or {}),
                str(job.get("verify_mode") or "size"),
                1 if job.get("delete_source_after_verify") else 0,
                job.get("target_root"),
                job.get("current_item_index"),
                str(job.get("current_path") or ""),
                int(job.get("bytes") or 0),
                int(job.get("total_bytes") or 0),
                int(job.get("files") or 0),
                int(job.get("total_files") or 0),
                int(job.get("skipped") or 0),
                int(job.get("skipped_bytes") or 0),
                int(job.get("manifest_files") or 0),
                int(job.get("manifest_directories") or 0),
                _json(job.get("warnings") or []),
                job.get("error"),
                float(job.get("progress_percent") or 0),
                float(job.get("average_mib_s") or 0),
                int(job.get("wait_cycles") or 0),
                int(job.get("auto_resumes") or 0),
                job.get("waiting_since"),
                job.get("lease_owner"),
                job.get("lease_expires_at"),
                job["created_at"],
                job["updated_at"],
                job.get("finished_at"),
            ),
        )
        connection.commit()


def update_job(job_id: str, **changes: Any) -> None:
    if not changes:
        return
    invalid = set(changes) - JOB_FIELDS
    if invalid:
        raise ValueError(f"unsupported StreamCopy job fields: {sorted(invalid)}")
    if "warnings_json" in changes and not isinstance(changes["warnings_json"], str):
        changes["warnings_json"] = _json(changes["warnings_json"])
    if "updated_at" not in changes:
        changes["updated_at"] = now_iso()
    assignments = ", ".join(f"{key} = ?" for key in changes)
    with connect() as connection:
        connection.execute(
            f"UPDATE streamcopy_jobs SET {assignments} WHERE id = ?",
            [*changes.values(), job_id],
        )
        connection.commit()


def _decode_job(row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "type": "streamcopy_experimental",
        "status": str(row["status"]),
        "source_path": str(row["source_path"]),
        "destination_path": str(row["destination_path"]),
        "source_endpoint": json.loads(row["source_endpoint_json"] or "{}"),
        "destination_endpoint": json.loads(row["destination_endpoint_json"] or "{}"),
        "profile": json.loads(row["profile_json"] or "{}"),
        "verify_mode": str(row["verify_mode"] or "size"),
        "delete_source_after_verify": bool(row["delete_source_after_verify"]),
        "target_root": row["target_root"],
        "current_item_index": row["current_item_index"],
        "current_path": str(row["current_path"] or ""),
        "bytes": int(row["bytes"] or 0),
        "total_bytes": int(row["total_bytes"] or 0),
        "files": int(row["files"] or 0),
        "total_files": int(row["total_files"] or 0),
        "skipped": int(row["skipped"] or 0),
        "skipped_bytes": int(row["skipped_bytes"] or 0),
        "manifest_files": int(row["manifest_files"] or 0),
        "manifest_directories": int(row["manifest_directories"] or 0),
        "warnings": json.loads(row["warnings_json"] or "[]"),
        "error": row["error"],
        "progress_percent": float(row["progress_percent"] or 0),
        "average_mib_s": float(row["average_mib_s"] or 0),
        "wait_cycles": int(row["wait_cycles"] or 0),
        "auto_resumes": int(row["auto_resumes"] or 0),
        "waiting_since": row["waiting_since"],
        "lease_owner": row["lease_owner"],
        "lease_expires_at": row["lease_expires_at"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "finished_at": row["finished_at"],
        "persistent": True,
    }


def get_job(job_id: str) -> dict[str, Any]:
    init_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM streamcopy_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    if row is None:
        raise KeyError(job_id)
    return _decode_job(row)


def list_jobs(*, active_only: bool = False, limit: int = 20) -> list[dict[str, Any]]:
    init_database()
    bounded = max(1, min(100, int(limit)))
    params: list[Any] = []
    where = ""
    if active_only:
        placeholders = ",".join("?" for _ in TERMINAL_STATES)
        where = f"WHERE status NOT IN ({placeholders})"
        params.extend(sorted(TERMINAL_STATES))
    params.append(bounded)
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM streamcopy_jobs
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_decode_job(row) for row in rows]


def replace_manifest(
    job_id: str,
    *,
    target_root: str,
    items: list[dict[str, Any]],
    directory_count: int,
) -> None:
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM streamcopy_checkpoints WHERE job_id = ?", (job_id,))
        connection.execute("DELETE FROM streamcopy_items WHERE job_id = ?", (job_id,))
        connection.executemany(
            """
            INSERT INTO streamcopy_items (
                job_id, item_index, source_path, target_path, partial_path,
                size, source_mtime_ns, status, confirmed_offset, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL)
            """,
            [
                (
                    job_id,
                    int(item["item_index"]),
                    str(item["source_path"]),
                    str(item["target_path"]),
                    str(item["partial_path"]),
                    int(item["size"]),
                    item.get("source_mtime_ns"),
                )
                for item in items
            ],
        )
        total_bytes = sum(int(item["size"]) for item in items)
        connection.execute(
            """
            UPDATE streamcopy_jobs
            SET target_root = ?,
                total_files = ?,
                total_bytes = ?,
                manifest_files = ?,
                manifest_directories = ?,
                bytes = 0,
                files = 0,
                current_item_index = NULL,
                current_path = '',
                progress_percent = 0,
                updated_at = ?
            WHERE id = ?
            """,
            (
                target_root,
                len(items),
                total_bytes,
                len(items),
                int(directory_count),
                now_iso(),
                job_id,
            ),
        )
        connection.commit()


def list_items(job_id: str) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM streamcopy_items
            WHERE job_id = ?
            ORDER BY item_index
            """,
            (job_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_item(job_id: str, item_index: int) -> dict[str, Any]:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM streamcopy_items
            WHERE job_id = ? AND item_index = ?
            """,
            (job_id, int(item_index)),
        ).fetchone()
    if row is None:
        raise KeyError((job_id, item_index))
    return dict(row)


def update_item(job_id: str, item_index: int, **changes: Any) -> None:
    if not changes:
        return
    invalid = set(changes) - ITEM_FIELDS
    if invalid:
        raise ValueError(f"unsupported StreamCopy item fields: {sorted(invalid)}")
    assignments = ", ".join(f"{key} = ?" for key in changes)
    with connect() as connection:
        connection.execute(
            f"""
            UPDATE streamcopy_items
            SET {assignments}
            WHERE job_id = ? AND item_index = ?
            """,
            [*changes.values(), job_id, int(item_index)],
        )
        connection.commit()


def add_checkpoint(
    job_id: str,
    item_index: int,
    *,
    offset: int,
    block_start: int,
    block_size: int,
    digest: str,
) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO streamcopy_checkpoints (
                job_id, item_index, offset, block_start, block_size, digest
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                int(item_index),
                int(offset),
                int(block_start),
                int(block_size),
                str(digest),
            ),
        )
        connection.execute(
            """
            UPDATE streamcopy_items
            SET confirmed_offset = ?
            WHERE job_id = ? AND item_index = ?
            """,
            (int(offset), job_id, int(item_index)),
        )
        connection.commit()


def list_checkpoints(job_id: str, item_index: int) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT offset, block_start, block_size, digest
            FROM streamcopy_checkpoints
            WHERE job_id = ? AND item_index = ?
            ORDER BY offset DESC
            """,
            (job_id, int(item_index)),
        ).fetchall()
    return [dict(row) for row in rows]


def discard_checkpoints_after(job_id: str, item_index: int, offset: int) -> None:
    with connect() as connection:
        connection.execute(
            """
            DELETE FROM streamcopy_checkpoints
            WHERE job_id = ? AND item_index = ? AND offset > ?
            """,
            (job_id, int(item_index), int(offset)),
        )
        connection.execute(
            """
            UPDATE streamcopy_items
            SET confirmed_offset = ?
            WHERE job_id = ? AND item_index = ?
            """,
            (int(offset), job_id, int(item_index)),
        )
        connection.commit()


def claim_job(job_id: str, owner: str, lease_seconds: float) -> bool:
    now = time.time()
    expires = now + float(lease_seconds)
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            """
            SELECT status, lease_owner, lease_expires_at
            FROM streamcopy_jobs
            WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None or str(row["status"]) in TERMINAL_STATES:
            connection.rollback()
            return False
        lease_owner = row["lease_owner"]
        lease_expires = float(row["lease_expires_at"] or 0)
        if lease_owner and lease_owner != owner and lease_expires > now:
            connection.rollback()
            return False
        connection.execute(
            """
            UPDATE streamcopy_jobs
            SET lease_owner = ?, lease_expires_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (owner, expires, now_iso(), job_id),
        )
        connection.commit()
    return True


def renew_lease(job_id: str, owner: str, lease_seconds: float) -> bool:
    expires = time.time() + float(lease_seconds)
    with connect() as connection:
        cursor = connection.execute(
            """
            UPDATE streamcopy_jobs
            SET lease_expires_at = ?, updated_at = ?
            WHERE id = ? AND lease_owner = ?
            """,
            (expires, now_iso(), job_id, owner),
        )
        connection.commit()
    return cursor.rowcount == 1


def release_lease(job_id: str, owner: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE streamcopy_jobs
            SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
            WHERE id = ? AND lease_owner = ?
            """,
            (now_iso(), job_id, owner),
        )
        connection.commit()



def summarize_items(job_id: str) -> dict[str, int]:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status = 'completed' THEN size ELSE 0 END), 0)
                    AS completed_bytes,
                COALESCE(SUM(CASE WHEN status = 'skipped' THEN size ELSE 0 END), 0)
                    AS skipped_bytes,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0)
                    AS completed_files,
                COALESCE(SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END), 0)
                    AS skipped_files
            FROM streamcopy_items
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
    return {
        "completed_bytes": int(row["completed_bytes"] or 0),
        "skipped_bytes": int(row["skipped_bytes"] or 0),
        "completed_files": int(row["completed_files"] or 0),
        "skipped_files": int(row["skipped_files"] or 0),
    }
