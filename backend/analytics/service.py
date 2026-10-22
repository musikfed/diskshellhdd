from __future__ import annotations

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

    return {
        "scan": dict(session),
        "categories": [dict(row) for row in categories],
        "top_files": [dict(row) for row in top_files],
        "top_directories": [dict(row) for row in top_directories],
        "extensions": [dict(row) for row in extension_rows],
    }
