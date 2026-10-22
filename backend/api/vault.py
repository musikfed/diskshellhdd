from __future__ import annotations

from flask import Blueprint, jsonify, make_response, request

from backend.vault.service import (
    SESSION_TTL_SECONDS,
    VaultError,
    VaultLocked,
    create_vault,
    export_file,
    import_file,
    list_items,
    lock,
    unlock,
    unlock_recovery,
    vault_status,
)


bp = Blueprint("vault", __name__, url_prefix="/api/vault")
COOKIE_NAME = "diskshell_vault"


def _token() -> str:
    return request.cookies.get(COOKIE_NAME, "")


def _unlocked_response(payload: dict):
    token = payload.pop("token")
    response = make_response(jsonify(payload))
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="Strict",
        secure=False,  # localhost HTTP; set True when HTTPS remote access is introduced.
        path="/api/vault",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/status")
def status():
    return jsonify(vault_status())


@bp.post("/create")
def create():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(create_vault(str(payload.get("identity", "")), str(payload.get("secret", "")))), 201
    except VaultError as exc:
        return jsonify({"error": "vault_create_failed", "message": str(exc)}), 400


@bp.post("/unlock")
def open_vault():
    payload = request.get_json(silent=True) or {}
    try:
        return _unlocked_response(unlock(str(payload.get("identity", "")), str(payload.get("secret", ""))))
    except VaultError as exc:
        return jsonify({"error": "vault_unlock_failed", "message": str(exc)}), 403


@bp.post("/unlock-recovery")
def open_vault_recovery():
    payload = request.get_json(silent=True) or {}
    try:
        return _unlocked_response(unlock_recovery(str(payload.get("recovery_key", ""))))
    except VaultError as exc:
        return jsonify({"error": "vault_unlock_failed", "message": str(exc)}), 403


@bp.post("/lock")
def close_vault():
    lock(_token())
    response = make_response(jsonify({"status": "locked"}))
    response.delete_cookie(COOKIE_NAME, path="/api/vault")
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/items")
def items():
    try:
        response = jsonify({"items": list_items(_token())})
        response.headers["Cache-Control"] = "no-store"
        return response
    except (VaultError, VaultLocked) as exc:
        return jsonify({"error": "vault_locked", "message": str(exc)}), 403


@bp.post("/import")
def import_item():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(import_file(_token(), str(payload["source"]))), 201
    except (KeyError, FileNotFoundError, VaultError, VaultLocked, OSError) as exc:
        return jsonify({"error": "vault_import_failed", "message": str(exc)}), 400


@bp.post("/export")
def export_item():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(export_file(_token(), str(payload["object_id"]), str(payload["destination"])))
    except (KeyError, FileNotFoundError, FileExistsError, VaultError, VaultLocked, OSError) as exc:
        return jsonify({"error": "vault_export_failed", "message": str(exc)}), 400
