from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from backend.core.database import connect, init_database


def _ensure_fts(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS file_catalog_fts
            USING fts5(
                path,
                name,
                parent_path,
                category,
                extension,
                tokenize='unicode61'
            )
            """
        )
        return True
    except sqlite3.OperationalError:
        return False


def begin_refresh(connection: sqlite3.Connection, root: Path, scan_id: int) -> None:
    connection.execute(
        """
        INSERT INTO file_catalog_roots(root_path,last_scan_id,status,files_count,refreshed_at)
        VALUES(?,?,'running',0,CURRENT_TIMESTAMP)
        ON CONFLICT(root_path) DO UPDATE SET
            last_scan_id=excluded.last_scan_id,
            status='running',
            refreshed_at=CURRENT_TIMESTAMP
        """,
        (str(root), int(scan_id)),
    )


def upsert_rows(connection: sqlite3.Connection, rows: Iterable[tuple[Any, ...]]) -> None:
    values = list(rows)
    if not values:
        return
    connection.executemany(
        """
        INSERT INTO file_catalog(
            path,parent_path,name,extension,category,size,
            modified_ns,accessed_ns,created_ns,last_scan_id,last_seen_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(path) DO UPDATE SET
            parent_path=excluded.parent_path,
            name=excluded.name,
            extension=excluded.extension,
            category=excluded.category,
            size=excluded.size,
            modified_ns=excluded.modified_ns,
            accessed_ns=excluded.accessed_ns,
            created_ns=excluded.created_ns,
            last_scan_id=excluded.last_scan_id,
            last_seen_at=CURRENT_TIMESTAMP
        """,
        [
            (
                str(row[1]),
                str(row[2]),
                str(row[3]),
                row[4],
                str(row[5]),
                int(row[6]),
                row[7],
                row[8],
                row[9],
                int(row[0]),
            )
            for row in values
        ],
    )

    if _ensure_fts(connection):
        paths = [str(row[1]) for row in values]
        connection.executemany(
            "DELETE FROM file_catalog_fts WHERE path = ?",
            [(path,) for path in paths],
        )
        connection.executemany(
            """
            INSERT INTO file_catalog_fts(path,name,parent_path,category,extension)
            VALUES(?,?,?,?,?)
            """,
            [
                (
                    str(row[1]),
                    str(row[3]),
                    str(row[2]),
                    str(row[5]),
                    str(row[4] or ""),
                )
                for row in values
            ],
        )


def _root_pattern(root: Path) -> tuple[str, str]:
    root_text = str(root)
    prefix = root_text.rstrip("\\/") + os.sep + "%"
    return root_text, prefix


def finish_refresh(
    connection: sqlite3.Connection,
    root: Path,
    scan_id: int,
    files_count: int,
) -> None:
    root_text, prefix = _root_pattern(root)
    stale = connection.execute(
        """
        SELECT path FROM file_catalog
        WHERE (path = ? OR path LIKE ?)
          AND COALESCE(last_scan_id, -1) <> ?
        """,
        (root_text, prefix, int(scan_id)),
    ).fetchall()
    stale_paths = [str(row["path"]) for row in stale]
    if stale_paths and _ensure_fts(connection):
        connection.executemany(
            "DELETE FROM file_catalog_fts WHERE path = ?",
            [(path,) for path in stale_paths],
        )
    connection.execute(
        """
        DELETE FROM file_catalog
        WHERE (path = ? OR path LIKE ?)
          AND COALESCE(last_scan_id, -1) <> ?
        """,
        (root_text, prefix, int(scan_id)),
    )
    connection.execute(
        """
        INSERT INTO file_catalog_roots(root_path,last_scan_id,status,files_count,refreshed_at)
        VALUES(?,?,'ready',?,CURRENT_TIMESTAMP)
        ON CONFLICT(root_path) DO UPDATE SET
            last_scan_id=excluded.last_scan_id,
            status='ready',
            files_count=excluded.files_count,
            refreshed_at=CURRENT_TIMESTAMP
        """,
        (root_text, int(scan_id), int(files_count)),
    )


def mark_refresh_status(
    connection: sqlite3.Connection,
    root: Path,
    scan_id: int | None,
    status: str,
) -> None:
    connection.execute(
        """
        INSERT INTO file_catalog_roots(root_path,last_scan_id,status,files_count,refreshed_at)
        VALUES(?,?,?,0,CURRENT_TIMESTAMP)
        ON CONFLICT(root_path) DO UPDATE SET
            last_scan_id=excluded.last_scan_id,
            status=excluded.status,
            refreshed_at=CURRENT_TIMESTAMP
        """,
        (str(root), scan_id, str(status)),
    )


def _fts_query(text: str) -> str:
    tokens = [
        token.replace('"', "")
        for token in text.strip().split()
        if token.replace('"', "").strip()
    ]
    return " AND ".join(f'"{token}"*' for token in tokens)


def search_files(
    query: str = "",
    *,
    root: str | None = None,
    category: str | None = None,
    extension: str | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    init_database()
    bounded_limit = max(1, min(1000, int(limit)))
    bounded_offset = max(0, int(offset))
    clean_query = str(query or "").strip()
    where = ["1=1"]
    params: list[Any] = []

    if root:
        root_value = str(Path(root).expanduser())
        where.append("(c.path = ? OR c.path LIKE ?)")
        params.extend([root_value, root_value.rstrip("\\/") + os.sep + "%"])
    if category:
        where.append("c.category = ?")
        params.append(str(category))
    if extension:
        value = str(extension).casefold()
        if value and not value.startswith("."):
            value = "." + value
        where.append("COALESCE(c.extension, '') = ?")
        params.append(value)
    if min_size is not None:
        where.append("c.size >= ?")
        params.append(int(min_size))
    if max_size is not None:
        where.append("c.size <= ?")
        params.append(int(max_size))

    with connect() as connection:
        fts_ready = _ensure_fts(connection)
        if clean_query and fts_ready:
            fts = _fts_query(clean_query)
            sql = f"""
                SELECT c.*
                FROM file_catalog_fts f
                JOIN file_catalog c ON c.path = f.path
                WHERE file_catalog_fts MATCH ?
                  AND {' AND '.join(where)}
                ORDER BY bm25(file_catalog_fts), c.size DESC
                LIMIT ? OFFSET ?
            """
            rows = connection.execute(
                sql,
                [fts, *params, bounded_limit, bounded_offset],
            ).fetchall()
        else:
            fallback_where = list(where)
            fallback_params = list(params)
            if clean_query:
                like = f"%{clean_query}%"
                fallback_where.append("(c.name LIKE ? COLLATE NOCASE OR c.path LIKE ? COLLATE NOCASE)")
                fallback_params.extend([like, like])
            rows = connection.execute(
                f"""
                SELECT c.*
                FROM file_catalog c
                WHERE {' AND '.join(fallback_where)}
                ORDER BY c.modified_ns DESC, c.size DESC
                LIMIT ? OFFSET ?
                """,
                [*fallback_params, bounded_limit, bounded_offset],
            ).fetchall()

    return {
        "query": clean_query,
        "fts": bool(clean_query and fts_ready),
        "limit": bounded_limit,
        "offset": bounded_offset,
        "files": [dict(row) for row in rows],
    }


def catalog_status() -> dict[str, Any]:
    init_database()
    with connect() as connection:
        total = int(connection.execute("SELECT COUNT(*) FROM file_catalog").fetchone()[0])
        roots = [
            dict(row)
            for row in connection.execute(
                """
                SELECT root_path,last_scan_id,status,files_count,refreshed_at
                FROM file_catalog_roots
                ORDER BY refreshed_at DESC
                """
            ).fetchall()
        ]
        fts = _ensure_fts(connection)
    return {"files": total, "roots": roots, "fts5": fts}
