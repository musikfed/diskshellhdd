from __future__ import annotations

from typing import Any

from backend.core.database import connect, init_database


PAGE_IDS = {
    "dashboard",
    "disks",
    "scan",
    "analytics",
    "storage",
    "files",
    "streamcopy",
    "people",
    "vault",
    "recovery",
    "diagnostics",
    "security",
    "lab",
}


def _ensure_row(connection) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO workspace_state
            (id, active_page, active_volume, scan_id)
        VALUES (1, 'dashboard', '', '')
        """
    )


def get_workspace_state() -> dict[str, Any]:
    init_database()
    with connect() as connection:
        _ensure_row(connection)
        row = connection.execute(
            """
            SELECT active_page, active_volume, scan_id, updated_at
            FROM workspace_state
            WHERE id = 1
            """
        ).fetchone()
        connection.commit()
    return {
        "active_page": str(row["active_page"] or "dashboard"),
        "active_volume": str(row["active_volume"] or ""),
        "scan_id": str(row["scan_id"] or ""),
        "updated_at": str(row["updated_at"] or ""),
        "scope": "local_backend",
        "browser_independent": True,
    }


def update_workspace_state(
    *,
    active_page: str | None = None,
    active_volume: str | None = None,
    scan_id: str | int | None = None,
) -> dict[str, Any]:
    init_database()

    updates: list[str] = []
    values: list[Any] = []

    if active_page is not None:
        page = str(active_page)
        if page not in PAGE_IDS:
            raise ValueError(f"unknown page: {page}")
        updates.append("active_page = ?")
        values.append(page)

    if active_volume is not None:
        updates.append("active_volume = ?")
        values.append(str(active_volume))

    if scan_id is not None:
        updates.append("scan_id = ?")
        values.append(str(scan_id))

    with connect() as connection:
        _ensure_row(connection)
        if updates:
            updates.append("updated_at = CURRENT_TIMESTAMP")
            connection.execute(
                f"UPDATE workspace_state SET {', '.join(updates)} WHERE id = 1",
                values,
            )
        connection.commit()

    return get_workspace_state()
