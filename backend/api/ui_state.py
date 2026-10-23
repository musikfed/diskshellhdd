from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.ui_state.service import get_workspace_state, update_workspace_state


bp = Blueprint("ui_state", __name__, url_prefix="/api/ui-state")


@bp.get("")
def workspace_state():
    return jsonify(get_workspace_state())


@bp.patch("")
@bp.post("")
def save_workspace_state():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(
            update_workspace_state(
                active_page=payload.get("active_page"),
                active_volume=payload.get("active_volume"),
                scan_id=payload.get("scan_id"),
                view_state=payload.get("view_state"),
            )
        )
    except ValueError as exc:
        return jsonify({"error": "workspace_state_invalid", "message": str(exc)}), 400
