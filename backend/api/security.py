from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.security.jobs import (
    cancel_security_job,
    get_security_job,
    recent_security_results,
    start_security_scan,
)
from backend.security.service import available_engines


bp = Blueprint("security", __name__, url_prefix="/api/security")


@bp.get("/engines")
def engines():
    return jsonify({"engines": available_engines()})


@bp.post("/scans")
def start_scan():
    payload = request.get_json(silent=True) or {}
    path = str(payload.get("path", "")).strip()
    if not path:
        return jsonify({"error": "missing_path"}), 400
    try:
        return jsonify(start_security_scan(path, str(payload.get("engine", "auto")))), 202
    except (FileNotFoundError, RuntimeError, OSError, ValueError) as exc:
        return jsonify({"error": "security_scan_failed", "message": str(exc)}), 400


@bp.get("/scans/<job_id>")
def scan_status(job_id: str):
    try:
        return jsonify(get_security_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404


@bp.post("/scans/<job_id>/cancel")
def cancel_scan(job_id: str):
    try:
        return jsonify(cancel_security_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404


@bp.get("/results")
def results():
    try:
        limit = int(request.args.get("limit", 20))
        return jsonify({"results": recent_security_results(limit)})
    except ValueError as exc:
        return jsonify({"error": "invalid_limit", "message": str(exc)}), 400
