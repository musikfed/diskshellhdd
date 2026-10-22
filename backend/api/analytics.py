from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.analytics.service import duplicate_candidates, exact_duplicates, summary


bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


@bp.get("/<int:scan_id>")
def analytics_summary(scan_id: int):
    try:
        return jsonify(summary(scan_id))
    except KeyError:
        return jsonify({"error": "scan_not_found"}), 404


@bp.get("/<int:scan_id>/duplicate-candidates")
def duplicates_candidates(scan_id: int):
    try:
        min_size = max(1, int(request.args.get("min_size", 1)))
        return jsonify(duplicate_candidates(scan_id, min_size=min_size))
    except ValueError as exc:
        return jsonify({"error": "invalid_argument", "message": str(exc)}), 400


@bp.post("/<int:scan_id>/duplicates")
def duplicates_exact(scan_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        min_size = max(1, int(payload.get("min_size", 1)))
        max_files = min(max(2, int(payload.get("max_files", 2000))), 20_000)
        return jsonify(exact_duplicates(scan_id, min_size=min_size, max_files=max_files))
    except ValueError as exc:
        return jsonify({"error": "invalid_argument", "message": str(exc)}), 400
