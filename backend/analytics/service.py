from __future__ import annotations

import hashlib
from pathlib import Path

from backend.core.database import connect


def summary(scan_id: int) -> dict:
    with connect() as connection:
        session = connection.execute(
            "SELECT * FROM scan_sessions WHERE id = ?", (scan_id,)
        ).fetchone()
        if session is None:
            raise KeyError(scan_id)

        categories = connection.execute(
            """
            SELECT category, COUNT(*) AS files, COALESCE(SUM(size), 0) AS bytes
            FROM files WHERE scan_id = ?
            GROUP BY category ORDER BY bytes DESC
            """,
            (scan_id,),
        ).fetchall()
        top_files = connection.execute(
            """
            SELECT path, name, category, size, modified_ns
            FROM files WHERE scan_id = ? ORDER BY size DESC LIMIT 25
            """,
            (scan_id,),
        ).fetchall()
        top_directories = connection.execute(
            """
            SELECT path, name, total_size, total_files
            FROM directories WHERE scan_id = ? ORDER BY total_size DESC LIMIT 25
            """,
            (scan_id,),
        ).fetchall()
        extension_rows = connection.execute(
            """
            SELECT COALESCE(extension, '(none)') AS extension, COUNT(*) AS files,
                   COALESCE(SUM(size), 0) AS bytes
            FROM files WHERE scan_id = ?
            GROUP BY extension ORDER BY bytes DESC LIMIT 50
            """,
            (scan_id,),
        ).fetchall()
        duplicate_candidate_bytes = connection.execute(
            """
            SELECT COALESCE(SUM(size * (count - 1)), 0) AS bytes
            FROM (
                SELECT size, COUNT(*) AS count
                FROM files WHERE scan_id = ? AND size > 0
                GROUP BY size HAVING COUNT(*) > 1
            )
            """,
            (scan_id,),
        ).fetchone()["bytes"]

    return {
        "scan": dict(session),
        "categories": [dict(row) for row in categories],
        "top_files": [dict(row) for row in top_files],
        "top_directories": [dict(row) for row in top_directories],
        "extensions": [dict(row) for row in extension_rows],
        "duplicate_candidate_bytes": int(duplicate_candidate_bytes or 0),
    }


def duplicate_candidates(scan_id: int, min_size: int = 1, limit_groups: int = 200) -> dict:
    with connect() as connection:
        sizes = connection.execute(
            """
            SELECT size, COUNT(*) AS count
            FROM files
            WHERE scan_id = ? AND size >= ?
            GROUP BY size HAVING COUNT(*) > 1
            ORDER BY size * (COUNT(*) - 1) DESC
            LIMIT ?
            """,
            (scan_id, min_size, limit_groups),
        ).fetchall()
        groups = []
        for row in sizes:
            files = connection.execute(
                "SELECT id, path, name, size FROM files WHERE scan_id=? AND size=? ORDER BY path",
                (scan_id, row["size"]),
            ).fetchall()
            groups.append(
                {
                    "size": row["size"],
                    "count": row["count"],
                    "potential_savings": row["size"] * (row["count"] - 1),
                    "files": [dict(item) for item in files],
                }
            )
    return {"scan_id": scan_id, "groups": groups, "mode": "size_candidates"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def exact_duplicates(
    scan_id: int,
    min_size: int = 1,
    max_files: int = 2000,
) -> dict:
    candidates = duplicate_candidates(scan_id, min_size=min_size, limit_groups=1000)
    file_rows = [item for group in candidates["groups"] for item in group["files"]]
    if len(file_rows) > max_files:
        file_rows = file_rows[:max_files]

    by_digest: dict[tuple[int, str], list[dict]] = {}
    with connect() as connection:
        for row in file_rows:
            cached = connection.execute(
                "SELECT digest, size FROM file_hashes WHERE file_id=? AND algorithm='sha256'",
                (row["id"],),
            ).fetchone()
            digest = None
            path = Path(row["path"])
            if cached is not None and cached["size"] == row["size"]:
                digest = cached["digest"]
            elif path.is_file():
                try:
                    digest = _sha256(path)
                except (PermissionError, FileNotFoundError, OSError):
                    continue
                connection.execute(
                    """
                    INSERT INTO file_hashes(file_id, algorithm, digest, size)
                    VALUES (?, 'sha256', ?, ?)
                    ON CONFLICT(file_id) DO UPDATE SET
                        algorithm='sha256', digest=excluded.digest, size=excluded.size,
                        hashed_at=CURRENT_TIMESTAMP
                    """,
                    (row["id"], digest, row["size"]),
                )
            if digest:
                by_digest.setdefault((row["size"], digest), []).append(row)
        connection.commit()

    groups = []
    for (size, digest), files in by_digest.items():
        if len(files) < 2:
            continue
        groups.append(
            {
                "size": size,
                "digest": digest,
                "count": len(files),
                "savings": size * (len(files) - 1),
                "files": files,
            }
        )
    groups.sort(key=lambda group: group["savings"], reverse=True)
    return {
        "scan_id": scan_id,
        "mode": "sha256_exact",
        "groups": groups,
        "hashed_files": len(file_rows),
        "potential_savings": sum(group["savings"] for group in groups),
    }
