from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.core.jobs import get_job, start_scan_job


bp = Blueprint("scans", __name__, url_prefix="/api/scans")


@bp.post("")
def start_scan():
    payload = request.get_json(silent=True) or {}
    path = payload.get("path")
    if not isinstance(path, str) or not path.strip():
        return jsonify({"error": "missing_path", "message": "Field path is required"}), 400
    try:
        job = start_scan_job(path.strip())
    except FileNotFoundError:
        return jsonify({"error": "path_not_found", "message": f"Path not found: {path}"}), 404
    except (NotADirectoryError, ValueError) as exc:
        return jsonify({"error": "invalid_path", "message": str(exc)}), 400
    return jsonify(job), 202


@bp.get("/<job_id>")
def scan_status(job_id: str):
    try:
        return jsonify(get_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404
