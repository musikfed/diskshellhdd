from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.files.service import FileWriteBlocked
from backend.streamcopy.jobs import (
    cancel_streamcopy_job,
    get_streamcopy_job,
    start_streamcopy_job,
    stream_profile,
)


bp = Blueprint("streamcopy", __name__, url_prefix="/api/streamcopy")


@bp.post("/profile")
def profile():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(
            stream_profile(
                str(payload.get("source_media") or "hdd"),
                str(payload.get("destination_media") or "hdd"),
                str(payload.get("source_transport") or "unknown"),
                str(payload.get("destination_transport") or "unknown"),
                str(payload.get("usb_topology") or "unknown"),
                payload.get("source_cache_mib"),
                payload.get("destination_cache_mib"),
            )
        )
    except ValueError as exc:
        return jsonify({"error": "streamcopy_profile_invalid", "message": str(exc)}), 400


@bp.post("/jobs")
def start_job():
    payload = request.get_json(silent=True) or {}
    try:
        job = start_streamcopy_job(
            source_path=str(payload["source_path"]),
            destination_path=str(payload["destination_path"]),
            source_media=str(payload.get("source_media") or "hdd"),
            destination_media=str(payload.get("destination_media") or "hdd"),
            source_transport=str(payload.get("source_transport") or "unknown"),
            destination_transport=str(payload.get("destination_transport") or "unknown"),
            usb_topology=str(payload.get("usb_topology") or "unknown"),
            source_cache_mib=payload.get("source_cache_mib"),
            destination_cache_mib=payload.get("destination_cache_mib"),
        )
        return jsonify(job), 202
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return jsonify({"error": "streamcopy_job_failed", "message": str(exc)}), 400


@bp.get("/jobs/<job_id>")
def job_status(job_id: str):
    try:
        return jsonify(get_streamcopy_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404


@bp.post("/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    try:
        return jsonify(cancel_streamcopy_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404
