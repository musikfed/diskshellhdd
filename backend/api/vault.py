from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.vault.service import (
    VaultError,
    VaultLocked,
    create_vault,
    export_file,
    import_file,
    list_items,
    lock,
    unlock,
    unlock_recovery,
)


bp = Blueprint("vault", __name__, url_prefix="/api/vault")


def _token() -> str:
    return request.headers.get("X-DiskShell-Vault-Token", "")


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
        return jsonify(unlock(str(payload.get("identity", "")), str(payload.get("secret", ""))))
    except VaultError as exc:
        return jsonify({"error": "vault_unlock_failed", "message": str(exc)}), 403


@bp.post("/unlock-recovery")
def open_vault_recovery():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(unlock_recovery(str(payload.get("recovery_key", ""))))
    except VaultError as exc:
        return jsonify({"error": "vault_unlock_failed", "message": str(exc)}), 403


@bp.post("/lock")
def close_vault():
    lock(_token())
    return jsonify({"status": "locked"})


@bp.get("/items")
def items():
    try:
        return jsonify({"items": list_items(_token())})
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
        return jsonify(
            export_file(
                _token(),
                str(payload["object_id"]),
                str(payload["destination"]),
            )
        )
    except (KeyError, FileNotFoundError, VaultError, VaultLocked, OSError) as exc:
        return jsonify({"error": "vault_export_failed", "message": str(exc)}), 400
