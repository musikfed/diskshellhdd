from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.archives.service import UnsupportedArchive, list_archive
from backend.preview.service import preview_metadata
from backend.vision.service import capabilities, detect_faces


bp = Blueprint("content", __name__, url_prefix="/api/content")


@bp.get("/preview")
def preview():
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "missing_path"}), 400
    try:
        return jsonify(preview_metadata(path))
    except (FileNotFoundError, OSError, ValueError) as exc:
        return jsonify({"error": "preview_failed", "message": str(exc)}), 400


@bp.get("/archive")
def archive():
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "missing_path"}), 400
    try:
        return jsonify(list_archive(path))
    except (FileNotFoundError, OSError, UnsupportedArchive, ValueError) as exc:
        return jsonify({"error": "archive_failed", "message": str(exc)}), 400


@bp.get("/vision/capabilities")
def vision_capabilities():
    return jsonify(capabilities())


@bp.get("/vision/faces")
def faces():
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "missing_path"}), 400
    try:
        return jsonify(detect_faces(path))
    except (FileNotFoundError, OSError, ValueError) as exc:
        return jsonify({"error": "face_detection_failed", "message": str(exc)}), 400
