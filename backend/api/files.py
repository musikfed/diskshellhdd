from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.files.service import FileWriteBlocked, copy_item, hash_file, list_directory, make_directory, move_item, trash_item


bp = Blueprint("files", __name__, url_prefix="/api/files")


@bp.get("")
def browse():
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "missing_path"}), 400
    try:
        return jsonify(list_directory(path))
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        return jsonify({"error": "browse_failed", "message": str(exc)}), 400


@bp.get("/hash")
def digest():
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "missing_path"}), 400
    try:
        return jsonify(hash_file(path, request.args.get("algorithm", "sha256")))
    except (FileNotFoundError, ValueError, OSError) as exc:
        return jsonify({"error": "hash_failed", "message": str(exc)}), 400


def _write_operation(operation):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(operation(payload["source"], payload["destination"]))
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except (KeyError, FileNotFoundError, FileExistsError, OSError) as exc:
        return jsonify({"error": "file_operation_failed", "message": str(exc)}), 400


@bp.post("/copy")
def copy():
    return _write_operation(copy_item)


@bp.post("/move")
def move():
    return _write_operation(move_item)


@bp.post("/mkdir")
def mkdir():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(make_directory(payload["path"])), 201
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except (KeyError, FileExistsError, FileNotFoundError, OSError) as exc:
        return jsonify({"error": "mkdir_failed", "message": str(exc)}), 400


@bp.post("/trash")
def trash():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(trash_item(payload["path"]))
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except (KeyError, FileNotFoundError, OSError) as exc:
        return jsonify({"error": "trash_failed", "message": str(exc)}), 400
