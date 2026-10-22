from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.commander.jobs import (
    cancel_commander_job,
    get_commander_job,
    start_commander_batch_job,
    start_commander_job,
)
from backend.files.service import FileWriteBlocked
from backend.files.write_authorization import file_writes_allowed
from backend.remote.service import (
    RemoteConnectionError,
    cache_remote_file,
    create_profile,
    delete_item,
    delete_profile,
    list_directory,
    list_profiles,
    make_directory,
    rename_item,
)


bp = Blueprint("commander", __name__, url_prefix="/api/commander")


def _require_file_writes() -> None:
    if not file_writes_allowed():
        raise FileWriteBlocked("File writes are locked")


@bp.get("/connections")
def connections():
    return jsonify({"connections": list_profiles()})


@bp.post("/connections")
def connect():
    payload = request.get_json(silent=True) or {}
    try:
        return (
            jsonify(
                create_profile(
                    protocol=str(payload["protocol"]),
                    host=str(payload["host"]),
                    username=str(payload["username"]),
                    password=str(payload.get("password") or ""),
                    port=(
                        int(payload["port"])
                        if payload.get("port") not in {None, ""}
                        else None
                    ),
                    private_key_path=str(payload.get("private_key_path") or ""),
                    accept_unknown_host=bool(payload.get("accept_unknown_host", False)),
                    passive=bool(payload.get("passive", True)),
                    root=str(payload.get("root") or "/"),
                )
            ),
            201,
        )
    except (KeyError, TypeError, ValueError, RemoteConnectionError, OSError) as exc:
        return jsonify({"error": "remote_connect_failed", "message": str(exc)}), 400


@bp.delete("/connections/<profile_id>")
def disconnect(profile_id: str):
    try:
        return jsonify(delete_profile(profile_id))
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except KeyError:
        return jsonify({"error": "connection_not_found"}), 404


@bp.get("/remote")
def remote_browse():
    profile_id = request.args.get("connection_id")
    path = request.args.get("path", "/")
    if not profile_id:
        return jsonify({"error": "missing_connection_id"}), 400
    try:
        return jsonify(list_directory(profile_id, path))
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except KeyError:
        return jsonify({"error": "connection_not_found"}), 404
    except (RemoteConnectionError, OSError, ValueError) as exc:
        return jsonify({"error": "remote_browse_failed", "message": str(exc)}), 400


@bp.post("/remote/mkdir")
def remote_mkdir():
    payload = request.get_json(silent=True) or {}
    try:
        _require_file_writes()
        return jsonify(make_directory(str(payload["connection_id"]), str(payload["path"]))), 201
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except KeyError:
        return jsonify({"error": "connection_not_found"}), 404
    except (RemoteConnectionError, OSError, ValueError) as exc:
        return jsonify({"error": "remote_mkdir_failed", "message": str(exc)}), 400


@bp.post("/remote/rename")
def remote_rename():
    payload = request.get_json(silent=True) or {}
    try:
        _require_file_writes()
        return jsonify(
            rename_item(
                str(payload["connection_id"]),
                str(payload["source"]),
                str(payload["destination"]),
            )
        )
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except KeyError:
        return jsonify({"error": "connection_not_found"}), 404
    except (RemoteConnectionError, OSError, ValueError) as exc:
        return jsonify({"error": "remote_rename_failed", "message": str(exc)}), 400


@bp.post("/remote/delete")
def remote_delete():
    payload = request.get_json(silent=True) or {}
    try:
        _require_file_writes()
        return jsonify(
            delete_item(
                str(payload["connection_id"]),
                str(payload["path"]),
                recursive=bool(payload.get("recursive", False)),
            )
        )
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except KeyError:
        return jsonify({"error": "connection_not_found"}), 404
    except (RemoteConnectionError, OSError, ValueError) as exc:
        return jsonify({"error": "remote_delete_failed", "message": str(exc)}), 400


@bp.post("/jobs")
def start_job():
    payload = request.get_json(silent=True) or {}
    try:
        if "transfers" in payload:
            transfers = [
                {
                    "source": dict(item["source"]),
                    "destination": dict(item["destination"]),
                }
                for item in payload["transfers"]
            ]
            job = start_commander_batch_job(
                operation=str(payload["operation"]),
                transfers=transfers,
            )
        else:
            job = start_commander_job(
                operation=str(payload["operation"]),
                source=dict(payload["source"]),
                destination=dict(payload["destination"]),
            )
        return jsonify(job), 202
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except (
        KeyError,
        TypeError,
        ValueError,
        FileNotFoundError,
        FileExistsError,
        RemoteConnectionError,
        OSError,
    ) as exc:
        return jsonify({"error": "commander_job_failed", "message": str(exc)}), 400


@bp.get("/jobs/<job_id>")
def job_status(job_id: str):
    try:
        return jsonify(get_commander_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404


@bp.post("/jobs/<job_id>/cancel")
def cancel_job(job_id: str):
    try:
        return jsonify(cancel_commander_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404


@bp.post("/remote/cache")
def remote_cache():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(
            cache_remote_file(
                str(payload["connection_id"]),
                str(payload["path"]),
                max_bytes=int(payload.get("max_bytes") or 256 * 1024**2),
            )
        )
    except FileWriteBlocked as exc:
        return jsonify({"error": "file_write_blocked", "message": str(exc)}), 403
    except KeyError:
        return jsonify({"error": "connection_not_found"}), 404
    except (RemoteConnectionError, OSError, ValueError, IsADirectoryError) as exc:
        return jsonify({"error": "remote_cache_failed", "message": str(exc)}), 400
