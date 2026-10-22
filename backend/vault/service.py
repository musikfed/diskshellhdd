from __future__ import annotations

import base64
import json
import os
import secrets
import time
import uuid
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.config import settings


SESSION_TTL_SECONDS = 15 * 60
_sessions: dict[str, dict] = {}


class VaultError(RuntimeError):
    pass


class VaultLocked(VaultError):
    pass


def _vault_root() -> Path:
    root = settings.data_dir / "vault"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _derive_kek(identity: str, secret: str, salt: bytes) -> bytes:
    material = f"{identity}\0{secret}".encode("utf-8")
    return hash_secret_raw(
        secret=material,
        salt=salt,
        time_cost=3,
        memory_cost=65536,
        parallelism=2,
        hash_len=32,
        type=Type.ID,
    )


def _seal(key: bytes, plaintext: bytes, aad: bytes) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    return nonce, AESGCM(key).encrypt(nonce, plaintext, aad)


def _open(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    return AESGCM(key).decrypt(nonce, ciphertext, aad)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def create_vault(identity: str, secret: str) -> dict:
    if not settings.allow_vault_writes:
        raise VaultError("DS_ALLOW_VAULT_WRITES is disabled")
    root = _vault_root()
    header_path = root / "vault.json"
    if header_path.exists():
        raise VaultError("Vault already exists")
    if len(secret) < 8:
        raise VaultError("Vault secret must be at least 8 characters")

    salt = os.urandom(16)
    master_key = os.urandom(32)
    kek = _derive_kek(identity, secret, salt)
    wrap_nonce, wrapped_master = _seal(kek, master_key, b"diskshell-vault-master")

    recovery_key = os.urandom(32)
    recovery_nonce, recovery_wrapped = _seal(
        recovery_key, master_key, b"diskshell-vault-recovery"
    )
    header = {
        "version": 1,
        "salt": _b64(salt),
        "wrap_nonce": _b64(wrap_nonce),
        "wrapped_master": _b64(wrapped_master),
        "recovery_nonce": _b64(recovery_nonce),
        "recovery_wrapped": _b64(recovery_wrapped),
    }
    header_path.write_text(json.dumps(header, indent=2), encoding="utf-8")
    (root / "objects").mkdir(exist_ok=True)
    _save_catalog(master_key, [])
    return {"status": "created", "recovery_key": _b64(recovery_key)}


def unlock(identity: str, secret: str) -> dict:
    header = _read_header()
    kek = _derive_kek(identity, secret, _unb64(header["salt"]))
    try:
        master_key = _open(
            kek,
            _unb64(header["wrap_nonce"]),
            _unb64(header["wrapped_master"]),
            b"diskshell-vault-master",
        )
    except Exception as exc:  # noqa: BLE001
        raise VaultError("Invalid Vault identity/secret") from exc
    return _new_session(master_key)


def unlock_recovery(recovery_key: str) -> dict:
    header = _read_header()
    try:
        master_key = _open(
            _unb64(recovery_key),
            _unb64(header["recovery_nonce"]),
            _unb64(header["recovery_wrapped"]),
            b"diskshell-vault-recovery",
        )
    except Exception as exc:  # noqa: BLE001
        raise VaultError("Invalid recovery key") from exc
    return _new_session(master_key)


def _new_session(master_key: bytes) -> dict:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"key": master_key, "last_used": time.monotonic()}
    return {"status": "unlocked", "token": token, "expires_in": SESSION_TTL_SECONDS}


def lock(token: str) -> None:
    _sessions.pop(token, None)


def _session_key(token: str) -> bytes:
    session = _sessions.get(token)
    if session is None:
        raise VaultLocked("Vault is locked")
    if time.monotonic() - session["last_used"] > SESSION_TTL_SECONDS:
        _sessions.pop(token, None)
        raise VaultLocked("Vault session expired")
    session["last_used"] = time.monotonic()
    return bytes(session["key"])


def _read_header() -> dict:
    path = _vault_root() / "vault.json"
    if not path.exists():
        raise VaultError("Vault is not initialized")
    return json.loads(path.read_text(encoding="utf-8"))


def _catalog_path() -> Path:
    return _vault_root() / "catalog.bin"


def _save_catalog(master_key: bytes, entries: list[dict]) -> None:
    payload = json.dumps(entries, ensure_ascii=False).encode("utf-8")
    nonce, ciphertext = _seal(master_key, payload, b"diskshell-vault-catalog")
    _catalog_path().write_bytes(nonce + ciphertext)


def _load_catalog(master_key: bytes) -> list[dict]:
    path = _catalog_path()
    if not path.exists():
        return []
    raw = path.read_bytes()
    payload = _open(master_key, raw[:12], raw[12:], b"diskshell-vault-catalog")
    return json.loads(payload.decode("utf-8"))


def list_items(token: str) -> list[dict]:
    return _load_catalog(_session_key(token))


def import_file(token: str, source: str | Path) -> dict:
    if not settings.allow_vault_writes:
        raise VaultError("DS_ALLOW_VAULT_WRITES is disabled")
    master_key = _session_key(token)
    source_path = Path(source).expanduser().resolve(strict=True)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    object_id = uuid.uuid4().hex
    plaintext = source_path.read_bytes()
    nonce, ciphertext = _seal(master_key, plaintext, object_id.encode("ascii"))
    (_vault_root() / "objects" / object_id).write_bytes(nonce + ciphertext)

    catalog = _load_catalog(master_key)
    item = {
        "id": object_id,
        "name": source_path.name,
        "size": len(plaintext),
        "source_path": str(source_path),
    }
    catalog.append(item)
    _save_catalog(master_key, catalog)
    return item


def export_file(token: str, object_id: str, destination: str | Path) -> dict:
    if not settings.allow_vault_writes:
        raise VaultError("DS_ALLOW_VAULT_WRITES is disabled")
    master_key = _session_key(token)
    catalog = _load_catalog(master_key)
    item = next((row for row in catalog if row["id"] == object_id), None)
    if item is None:
        raise FileNotFoundError(object_id)
    raw = (_vault_root() / "objects" / object_id).read_bytes()
    plaintext = _open(master_key, raw[:12], raw[12:], object_id.encode("ascii"))
    dest = Path(destination).expanduser().resolve()
    if dest.is_dir():
        dest = dest / item["name"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(plaintext)
    return {"status": "exported", "path": str(dest), "size": len(plaintext)}
