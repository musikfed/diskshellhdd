from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from backend.files.endpoint_availability import local_volume_probe
from backend.files.jobs import cancel_file_job, get_file_job, start_file_job
from backend.files.write_authorization import file_write_state, set_runtime_file_writes
from backend.storage_brain.service import suggest_managed_destination

from backend.files.service import (
    FileWriteBlocked,
    copy_item,
    hash_file,
    list_directory,
    list_roots,
    make_directory,
    move_item,
    rename_item,
    trash_item,
)


bp = Blueprint("files", __name__, url_prefix="/api/files")


@bp.get("")
def browse():
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "missing_path"}), 400
    raw_scan_id = request.args.get("scan_id")
    scan_id = int(raw_scan_id) if raw_scan_id not in {None, ""} else None
    state = local_volume_probe(path)
    if not state["available"]:
        return (
            jsonify(
                {
                    "error": "endpoint_unavailable",
                    "message": f"Volume is offline: {state['root']}",
                    "path": str(path),
                    "root": state["root"],
                }
            ),
            409,
        )
    try:
        return jsonify(list_directory(path, scan_id=scan_id))
    except (ValueError, FileNotFoundError, NotADirectoryError, OSError) as exc:
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


@bp.post("/jobs")
def start_job():
    payload = request.get_json(silent=True) or {}
    try:
        return (
            jsonify(
                start_file_job(
                    str(payload["operation"]),
                    str(payload["source"]),
                    str(payload["destination"]),
                )
            ),
            202,
        )
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except (KeyError, ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        return jsonify({"error": "file_job_failed", "message": str(exc)}), 400


@bp.get("/jobs/<job_id>")
def job_status(job_id: str):
    try:
        return jsonify(get_file_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404


@bp.post("/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    try:
        return jsonify(cancel_file_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404


@bp.post("/rename")
def rename():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(rename_item(payload["source"], payload["destination"]))
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except (KeyError, FileNotFoundError, FileExistsError, OSError) as exc:
        return jsonify({"error": "rename_failed", "message": str(exc)}), 400


@bp.post("/smart-destination")
def smart_destination():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(
            suggest_managed_destination(
                source_name=str(payload["name"]),
                source_path=str(payload.get("source_path") or payload["name"]),
                size=int(payload.get("size") or 0),
                modified_ns=(
                    int(payload["modified_ns"])
                    if payload.get("modified_ns") is not None
                    else None
                ),
                storage_root=Path(str(payload["storage_root"])),
            )
        )
    except (KeyError, ValueError, FileNotFoundError, OSError) as exc:
        return jsonify({"error": "smart_destination_failed", "message": str(exc)}), 400


@bp.post("/smart-destinations")
def smart_destinations():
    payload = request.get_json(silent=True) or {}
    try:
        raw_items = list(payload["items"])
        if not raw_items:
            return jsonify({"items": []})
        if len(raw_items) > 4000:
            raise ValueError("too many items; maximum is 4000")
        storage_root = Path(str(payload["storage_root"]))
        results = []
        for item in raw_items:
            source_path = str(item.get("source_path") or item["name"])
            result = suggest_managed_destination(
                source_name=str(item["name"]),
                source_path=source_path,
                size=int(item.get("size") or 0),
                modified_ns=(
                    int(item["modified_ns"])
                    if item.get("modified_ns") is not None
                    else None
                ),
                storage_root=storage_root,
            )
            result["source_path"] = source_path
            results.append(result)
        return jsonify({"items": results})
    except (KeyError, TypeError, ValueError, FileNotFoundError, OSError) as exc:
        return jsonify(
            {"error": "smart_destinations_failed", "message": str(exc)}
        ), 400


@bp.get("/roots")
def roots():
    return jsonify(list_roots())


@bp.get("/write-access")
def get_write_access():
    return jsonify(file_write_state())


@bp.post("/write-access")
def set_write_access():
    payload = request.get_json(silent=True) or {}
    if "enabled" not in payload:
        return jsonify({"error": "missing_enabled"}), 400
    return jsonify(set_runtime_file_writes(bool(payload["enabled"])))
