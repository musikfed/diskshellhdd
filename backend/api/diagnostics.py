from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.diagnostics.jobs import (
    cancel_surface_job,
    get_surface_job,
    recent_diagnostics,
    start_surface_job,
)
from backend.services.storage.windows_privileges import WindowsElevationRequired


bp = Blueprint("diagnostics", __name__, url_prefix="/api/diagnostics")


@bp.get("/history")
def history():
    try:
        limit = int(request.args.get("limit", 10))
        return jsonify({"runs": recent_diagnostics(limit)})
    except (TypeError, ValueError) as exc:
        return jsonify({"error": "history_failed", "message": str(exc)}), 400


@bp.post("/surface")
def start_surface():
    payload = request.get_json(silent=True) or {}
    try:
        disk_number = int(payload["disk_number"])
        mode = str(payload.get("mode", "quick"))
        return jsonify(start_surface_job(disk_number, mode)), 202
    except WindowsElevationRequired as exc:
        return jsonify({"error": "elevation_required", "message": str(exc)}), 403
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return jsonify({"error": "surface_start_failed", "message": str(exc)}), 400


@bp.get("/surface/<job_id>")
def surface_status(job_id: str):
    try:
        return jsonify(get_surface_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404


@bp.post("/surface/<job_id>/cancel")
def surface_cancel(job_id: str):
    try:
        return jsonify(cancel_surface_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404
