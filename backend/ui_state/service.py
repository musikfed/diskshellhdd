from __future__ import annotations

import json
from typing import Any

from backend.core.database import connect, init_database
from backend.core.events import emit_event


PAGE_IDS = {
    "dashboard",
    "disks",
    "scan",
    "analytics",
    "storage",
    "files",
    "search",
    "relocation",
    "streamcopy",
    "people",
    "vault",
    "recovery",
    "diagnostics",
    "security",
    "lab",
}

# Job ids belong to one concrete browser view. They must never be copied into
# the promoted default workspace, otherwise a brand-new tab can attach itself
# to work owned by another tab and start polling/cancelling the wrong job.
TRANSIENT_VIEW_STATE_KEYS = {
    "commanderJobId",
    "streamcopyJobId",
    "scanJobId",
    "placementJobId",
    "diagnosticJobId",
    "securityJobId",
}


def _default_view_state(raw: str | None) -> str:
    value = _decode_view_state(raw)
    for key in TRANSIENT_VIEW_STATE_KEYS:
        value.pop(key, None)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_view_state(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _state_from_row(
    row,
    *,
    view_id: str | None = None,
    inherited_default: bool = False,
) -> dict[str, Any]:
    return {
        "active_page": str(row["active_page"] or "dashboard"),
        "active_volume": str(row["active_volume"] or ""),
        "scan_id": str(row["scan_id"] or ""),
        "view_state": _decode_view_state(row["view_state_json"]),
        "updated_at": str(row["updated_at"] or ""),
        "scope": "local_backend",
        "browser_independent": True,
        "view_id": view_id,
        "view_isolation": bool(view_id),
        "inherited_default": bool(inherited_default),
        "detached": bool(row["detached"]) if "detached" in row.keys() else False,
    }


def _validate_view_id(view_id: str | None) -> str | None:
    if view_id is None:
        return None
    value = str(view_id).strip()
    if not value:
        return None
    if len(value) > 128:
        raise ValueError("view_id is too long")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:")
    if any(char not in allowed for char in value):
        raise ValueError("view_id contains unsupported characters")
    return value


def _read_default(connection):
    row = connection.execute(
        """
        SELECT active_page, active_volume, scan_id, view_state_json, updated_at
        FROM workspace_state
        WHERE id = 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("workspace_state row is missing after database initialization")
    return row


def get_workspace_state(view_id: str | None = None) -> dict[str, Any]:
    init_database()
    normalized_view_id = _validate_view_id(view_id)

    with connect() as connection:
        if normalized_view_id:
            row = connection.execute(
                """
                SELECT
                    active_page, active_volume, scan_id, view_state_json,
                    updated_at, detached
                FROM workspace_views
                WHERE view_id = ?
                """,
                (normalized_view_id,),
            ).fetchone()
            if row is not None:
                return _state_from_row(row, view_id=normalized_view_id)

        default_row = _read_default(connection)

    return _state_from_row(
        default_row,
        view_id=normalized_view_id,
        inherited_default=bool(normalized_view_id),
    )


def _merge_view_state(
    existing_json: str | None,
    patch: dict[str, Any] | None,
) -> str:
    existing = _decode_view_state(existing_json)
    if patch is None:
        merged = existing
    else:
        merged = dict(existing)
        for key, value in patch.items():
            if value is None:
                merged.pop(str(key), None)
            else:
                merged[str(key)] = value
    return json.dumps(merged, ensure_ascii=False, separators=(",", ":"))


def update_workspace_state(
    *,
    active_page: str | None = None,
    active_volume: str | None = None,
    scan_id: str | int | None = None,
    view_state: dict[str, Any] | None = None,
    view_id: str | None = None,
    detached: bool = False,
    promote_default: bool = True,
) -> dict[str, Any]:
    init_database()
    normalized_view_id = _validate_view_id(view_id)

    if active_page is not None:
        page = str(active_page)
        if page not in PAGE_IDS:
            raise ValueError(f"unknown page: {page}")
    else:
        page = None

    if view_state is not None and not isinstance(view_state, dict):
        raise ValueError("view_state must be an object")

    with connect() as connection:
        default_row = _read_default(connection)

        if normalized_view_id:
            current = connection.execute(
                """
                SELECT
                    active_page, active_volume, scan_id, view_state_json,
                    updated_at, detached
                FROM workspace_views
                WHERE view_id = ?
                """,
                (normalized_view_id,),
            ).fetchone()
            base = current or default_row

            next_page = page if page is not None else str(base["active_page"] or "dashboard")
            next_volume = (
                str(active_volume)
                if active_volume is not None
                else str(base["active_volume"] or "")
            )
            next_scan_id = (
                str(scan_id)
                if scan_id is not None
                else str(base["scan_id"] or "")
            )
            next_view_state = _merge_view_state(
                base["view_state_json"],
                view_state,
            )

            connection.execute(
                """
                INSERT INTO workspace_views(
                    view_id, active_page, active_volume, scan_id,
                    view_state_json, detached, created_at, updated_at
                )
                VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                ON CONFLICT(view_id) DO UPDATE SET
                    active_page=excluded.active_page,
                    active_volume=excluded.active_volume,
                    scan_id=excluded.scan_id,
                    view_state_json=excluded.view_state_json,
                    detached=excluded.detached,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    normalized_view_id,
                    next_page,
                    next_volume,
                    next_scan_id,
                    next_view_state,
                    1 if detached else 0,
                ),
            )

            if promote_default and not detached:
                connection.execute(
                    """
                    UPDATE workspace_state
                    SET active_page=?, active_volume=?, scan_id=?,
                        view_state_json=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=1
                    """,
                    (
                        next_page,
                        next_volume,
                        next_scan_id,
                        _default_view_state(next_view_state),
                    ),
                )

            row = connection.execute(
                """
                SELECT
                    active_page, active_volume, scan_id, view_state_json,
                    updated_at, detached
                FROM workspace_views
                WHERE view_id = ?
                """,
                (normalized_view_id,),
            ).fetchone()
        else:
            next_page = (
                page if page is not None else str(default_row["active_page"] or "dashboard")
            )
            next_volume = (
                str(active_volume)
                if active_volume is not None
                else str(default_row["active_volume"] or "")
            )
            next_scan_id = (
                str(scan_id)
                if scan_id is not None
                else str(default_row["scan_id"] or "")
            )
            next_view_state = _merge_view_state(
                default_row["view_state_json"],
                view_state,
            )
            connection.execute(
                """
                UPDATE workspace_state
                SET active_page=?, active_volume=?, scan_id=?,
                    view_state_json=?, updated_at=CURRENT_TIMESTAMP
                WHERE id=1
                """,
                (
                    next_page,
                    next_volume,
                    next_scan_id,
                    next_view_state,
                ),
            )
            row = _read_default(connection)

        connection.commit()

    if row is None:
        raise RuntimeError("workspace state is missing after update")

    state = _state_from_row(row, view_id=normalized_view_id)
    emit_event(
        "workspace.changed",
        {
            "view_id": normalized_view_id,
            "active_page": state["active_page"],
            "active_volume": state["active_volume"],
            "scan_id": state["scan_id"],
            "view_state": state["view_state"],
            "updated_at": state["updated_at"],
            "detached": bool(detached),
            "promoted_default": bool(promote_default and not detached),
        },
    )
    return state
