from __future__ import annotations

import io

from flask import Blueprint, jsonify, request, send_file

from backend.archives.service import (
    ArchiveWriteBlocked,
    UnsupportedArchive,
    create_archive,
    extract_archive,
    list_archive,
)
from backend.preview.service import preview_metadata, thumbnail_bytes
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


@bp.get("/thumbnail")
def thumbnail():
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "missing_path"}), 400
    try:
        data, mime = thumbnail_bytes(path, int(request.args.get("size", "720")))
        return send_file(io.BytesIO(data), mimetype=mime, max_age=60)
    except (FileNotFoundError, OSError, ValueError) as exc:
        return jsonify({"error": "thumbnail_failed", "message": str(exc)}), 400


@bp.get("/archive")
def archive():
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "missing_path"}), 400
    try:
        return jsonify(list_archive(path))
    except (FileNotFoundError, OSError, UnsupportedArchive, ValueError) as exc:
        return jsonify({"error": "archive_failed", "message": str(exc)}), 400


@bp.post("/archive/extract")
def extract():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(extract_archive(str(payload["path"]), str(payload["destination"])))
    except ArchiveWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except (KeyError, FileNotFoundError, FileExistsError, OSError, UnsupportedArchive, ValueError) as exc:
        return jsonify({"error": "extract_failed", "message": str(exc)}), 400


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


@bp.post("/archive/create")
def create():
    payload = request.get_json(silent=True) or {}
    try:
        sources = [str(item) for item in payload["sources"]]
        return jsonify(
            create_archive(
                sources=sources,
                destination=str(payload["destination"]),
                archive_format=str(payload.get("format", "zip")),
            )
        ), 201
    except ArchiveWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except (
        KeyError,
        TypeError,
        FileNotFoundError,
        FileExistsError,
        OSError,
        UnsupportedArchive,
        ValueError,
    ) as exc:
        return jsonify({"error": "archive_create_failed", "message": str(exc)}), 400
