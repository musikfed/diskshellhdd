from __future__ import annotations

import base64
import json
import os
import secrets
import struct
import time
import uuid
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.config import settings


SESSION_TTL_SECONDS = 15 * 60
OBJECT_CHUNK_SIZE = 4 * 1024 * 1024
OBJECT_MAGIC = b"DSVO1\0"
_sessions: dict[str, dict] = {}


class VaultError(RuntimeError):
    pass


class VaultLocked(VaultError):
    pass


def vault_status() -> dict:
    root = settings.vault_root
    header = root / "vault.json"
    return {
        "initialized": header.exists(),
        "root": str(root),
        "writes_allowed": settings.allow_vault_writes,
        "session_ttl_seconds": SESSION_TTL_SECONDS,
        "encryption": "AES-256-GCM chunked objects + encrypted catalog",
        "kdf": "Argon2id",
    }


def _vault_root(create: bool = True) -> Path:
    root = settings.vault_root
    if create:
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
    if not identity.strip():
        raise VaultError("Vault identity is required")
    if len(secret) < 8:
        raise VaultError("Vault secret must be at least 8 characters")

    root = _vault_root()
    header_path = root / "vault.json"
    if header_path.exists():
        raise VaultError("Vault already exists")

    salt = os.urandom(16)
    master_key = os.urandom(32)
    kek = _derive_kek(identity, secret, salt)
    wrap_nonce, wrapped_master = _seal(kek, master_key, b"diskshell-vault-master")

    recovery_key = os.urandom(32)
    recovery_nonce, recovery_wrapped = _seal(
        recovery_key, master_key, b"diskshell-vault-recovery"
    )
    header = {
        "version": 2,
        "salt": _b64(salt),
        "wrap_nonce": _b64(wrap_nonce),
        "wrapped_master": _b64(wrapped_master),
        "recovery_nonce": _b64(recovery_nonce),
        "recovery_wrapped": _b64(recovery_wrapped),
        "object_format": "DSVO1",
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
    except Exception as exc:  # cryptography deliberately hides exact auth failure
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
    except Exception as exc:
        raise VaultError("Invalid recovery key") from exc
    return _new_session(master_key)


def _new_session(master_key: bytes) -> dict:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"key": master_key, "last_used": time.monotonic()}
    return {"status": "unlocked", "token": token, "expires_in": SESSION_TTL_SECONDS}


def lock(token: str) -> None:
    session = _sessions.pop(token, None)
    if session is not None:
        session["key"] = b""


def _session_key(token: str) -> bytes:
    session = _sessions.get(token)
    if session is None:
        raise VaultLocked("Vault is locked")
    if time.monotonic() - session["last_used"] > SESSION_TTL_SECONDS:
        lock(token)
        raise VaultLocked("Vault session expired")
    session["last_used"] = time.monotonic()
    return bytes(session["key"])


def _read_header() -> dict:
    path = _vault_root(create=False) / "vault.json"
    if not path.exists():
        raise VaultError("Vault is not initialized")
    return json.loads(path.read_text(encoding="utf-8"))


def _catalog_path() -> Path:
    return _vault_root() / "catalog.bin"


def _save_catalog(master_key: bytes, entries: list[dict]) -> None:
    payload = json.dumps(entries, ensure_ascii=False).encode("utf-8")
    nonce, ciphertext = _seal(master_key, payload, b"diskshell-vault-catalog")
    temp = _catalog_path().with_suffix(".tmp")
    temp.write_bytes(nonce + ciphertext)
    os.replace(temp, _catalog_path())


def _load_catalog(master_key: bytes) -> list[dict]:
    path = _catalog_path()
    if not path.exists():
        return []
    raw = path.read_bytes()
    payload = _open(master_key, raw[:12], raw[12:], b"diskshell-vault-catalog")
    return json.loads(payload.decode("utf-8"))


def list_items(token: str) -> list[dict]:
    return _load_catalog(_session_key(token))


def _encrypt_object(master_key: bytes, object_id: str, source: Path, destination: Path) -> int:
    cipher = AESGCM(master_key)
    total = 0
    temp = destination.with_suffix(".tmp")
    with source.open("rb") as src, temp.open("wb") as dst:
        dst.write(OBJECT_MAGIC)
        dst.write(struct.pack(">I", OBJECT_CHUNK_SIZE))
        index = 0
        while True:
            chunk = src.read(OBJECT_CHUNK_SIZE)
            if not chunk:
                break
            nonce = os.urandom(12)
            aad = f"{object_id}:{index}".encode("ascii")
            encrypted = cipher.encrypt(nonce, chunk, aad)
            dst.write(nonce)
            dst.write(struct.pack(">I", len(encrypted)))
            dst.write(encrypted)
            total += len(chunk)
            index += 1
    os.replace(temp, destination)
    return total


def _decrypt_object(master_key: bytes, object_id: str, source: Path, destination: Path) -> int:
    cipher = AESGCM(master_key)
    total = 0
    temp = destination.with_name(f".{destination.name}.diskshell-vault-export-{uuid.uuid4().hex}")
    with source.open("rb") as src, temp.open("wb") as dst:
        if src.read(len(OBJECT_MAGIC)) != OBJECT_MAGIC:
            raise VaultError("Unsupported or damaged Vault object")
        _chunk_size = struct.unpack(">I", src.read(4))[0]
        index = 0
        while True:
            nonce = src.read(12)
            if not nonce:
                break
            if len(nonce) != 12:
                raise VaultError("Damaged Vault object")
            length_raw = src.read(4)
            if len(length_raw) != 4:
                raise VaultError("Damaged Vault object")
            encrypted_len = struct.unpack(">I", length_raw)[0]
            encrypted = src.read(encrypted_len)
            if len(encrypted) != encrypted_len:
                raise VaultError("Damaged Vault object")
            aad = f"{object_id}:{index}".encode("ascii")
            plaintext = cipher.decrypt(nonce, encrypted, aad)
            dst.write(plaintext)
            total += len(plaintext)
            index += 1
    os.replace(temp, destination)
    return total


def _encrypt_catalog_item(
    master_key: bytes,
    source_path: Path,
    *,
    relative_path: str | None = None,
    source_root: str | None = None,
) -> tuple[dict, Path]:
    object_id = uuid.uuid4().hex
    object_path = _vault_root() / "objects" / object_id
    object_path.parent.mkdir(exist_ok=True)
    size = _encrypt_object(master_key, object_id, source_path, object_path)
    item = {
        "id": object_id,
        "name": source_path.name,
        "size": size,
        "source_path": str(source_path),
        "relative_path": relative_path or source_path.name,
        "source_root": source_root,
        "imported_at": time.time(),
    }
    return item, object_path


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def import_path(token: str, source: str | Path) -> dict:
    """Encrypt one file or a complete directory tree.

    Directory import is catalog-atomic: encrypted objects created by a failed
    batch are removed and the catalog is left unchanged.
    """
    if not settings.allow_vault_writes:
        raise VaultError("DS_ALLOW_VAULT_WRITES is disabled")

    master_key = _session_key(token)
    source_path = Path(source).expanduser().resolve(strict=True)
    vault_root = _vault_root().resolve()
    catalog = _load_catalog(master_key)

    if _path_is_within(source_path, vault_root):
        raise VaultError("Vault storage itself cannot be imported into Vault")

    if source_path.is_file():
        item, _object_path = _encrypt_catalog_item(master_key, source_path)
        catalog.append(item)
        _save_catalog(master_key, catalog)
        return {
            "status": "imported",
            "kind": "file",
            "files": 1,
            "bytes": int(item["size"]),
            "items": [item],
        }

    if not source_path.is_dir():
        raise FileNotFoundError(source_path)

    files = sorted(
        (
            path
            for path in source_path.rglob("*")
            if (
                path.is_file()
                and not path.is_symlink()
                and not _path_is_within(path.resolve(), vault_root)
            )
        ),
        key=lambda path: str(path).casefold(),
    )
    created_objects: list[Path] = []
    new_items: list[dict] = []
    try:
        for file_path in files:
            relative = str(file_path.relative_to(source_path))
            item, object_path = _encrypt_catalog_item(
                master_key,
                file_path,
                relative_path=relative,
                source_root=str(source_path),
            )
            created_objects.append(object_path)
            new_items.append(item)
        catalog.extend(new_items)
        _save_catalog(master_key, catalog)
    except Exception:
        for object_path in created_objects:
            try:
                object_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    return {
        "status": "imported",
        "kind": "directory",
        "source": str(source_path),
        "files": len(new_items),
        "bytes": sum(int(item["size"]) for item in new_items),
        "items": new_items,
    }


def import_file(token: str, source: str | Path) -> dict:
    """Backward-compatible single-file import."""
    result = import_path(token, source)
    if result["kind"] != "file":
        raise VaultError("Expected a file source")
    return result["items"][0]


def export_file(token: str, object_id: str, destination: str | Path) -> dict:
    if not settings.allow_vault_writes:
        raise VaultError("DS_ALLOW_VAULT_WRITES is disabled")
    master_key = _session_key(token)
    catalog = _load_catalog(master_key)
    item = next((row for row in catalog if row["id"] == object_id), None)
    if item is None:
        raise FileNotFoundError(object_id)
    dest = Path(destination).expanduser().resolve()
    if dest.exists() and dest.is_dir():
        relative = Path(str(item.get("relative_path") or item["name"]))
        dest = dest / relative
    if dest.exists():
        raise FileExistsError(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = _decrypt_object(master_key, object_id, _vault_root() / "objects" / object_id, dest)
    return {"status": "exported", "path": str(dest), "size": size}
