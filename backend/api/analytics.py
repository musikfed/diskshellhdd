from __future__ import annotations

from flask import Blueprint, jsonify

from backend.analytics.service import summary


bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")


@bp.get("/<int:scan_id>")
def analytics_summary(scan_id: int):
    try:
        return jsonify(summary(scan_id))
    except KeyError:
        return jsonify({"error": "scan_not_found"}), 404
