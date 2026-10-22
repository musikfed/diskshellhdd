from __future__ import annotations

import ctypes
import os
import threading
from pathlib import Path
from typing import Any


_known_lock = threading.Lock()
_known_volume_identities: dict[str, str] = {}


def _windows_volume_identity(root: Path) -> str | None:
    if os.name != "nt":
        return None

    kernel32 = ctypes.windll.kernel32
    mount = str(root)
    if not mount.endswith("\\"):
        mount += "\\"

    volume_name = ctypes.create_unicode_buffer(1024)
    if kernel32.GetVolumeNameForVolumeMountPointW(
        ctypes.c_wchar_p(mount),
        volume_name,
        len(volume_name),
    ):
        value = volume_name.value.strip()
        if value:
            return value.casefold()

    volume_label = ctypes.create_unicode_buffer(261)
    filesystem_name = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_uint32()
    max_component_length = ctypes.c_uint32()
    filesystem_flags = ctypes.c_uint32()
    if kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(mount),
        volume_label,
        len(volume_label),
        ctypes.byref(serial),
        ctypes.byref(max_component_length),
        ctypes.byref(filesystem_flags),
        filesystem_name,
        len(filesystem_name),
    ):
        return f"serial:{serial.value:08x}"
    return None


def _local_root(path: str | Path) -> Path:
    value = Path(path).expanduser()
    if os.name == "nt" and value.drive:
        return Path(value.drive + "\\")
    if value.anchor:
        return Path(value.anchor)
    resolved = value.resolve()
    return Path(resolved.anchor or "/")


def local_volume_probe(path: str | Path) -> dict[str, Any]:
    root = _local_root(path)
    root_key = str(root).casefold()
    try:
        available = root.exists()
    except OSError:
        available = False

    identity = None
    if available:
        try:
            identity = _windows_volume_identity(root)
            if identity is None:
                identity = f"st_dev:{root.stat().st_dev}"
        except OSError:
            available = False
            identity = None

    if identity:
        with _known_lock:
            _known_volume_identities[root_key] = identity
    else:
        with _known_lock:
            identity = _known_volume_identities.get(root_key)

    return {
        "root": str(root),
        "available": bool(available),
        "identity": identity,
        "identity_cached": bool(identity and not available),
    }


def bind_local_volume(endpoint: dict[str, Any]) -> dict[str, Any]:
    if endpoint.get("kind") != "local":
        return dict(endpoint)
    result = dict(endpoint)
    probe = local_volume_probe(result["path"])
    result["volume_root"] = probe["root"]
    if probe["identity"]:
        result["volume_identity"] = probe["identity"]
    elif os.name == "nt":
        # Never auto-resume onto an unknown Windows volume that merely reused
        # the same drive letter. The operator must restart the transfer after
        # that volume is online and can be bound to a concrete identity.
        result["volume_identity_required"] = True
    return result


def local_endpoint_state(endpoint: dict[str, Any]) -> dict[str, Any]:
    probe = local_volume_probe(endpoint["path"])
    expected = endpoint.get("volume_identity")
    current = probe.get("identity")
    if not probe["available"]:
        return {
            "available": False,
            "reason": "volume_offline",
            "root": probe["root"],
            "expected_identity": expected,
            "current_identity": current,
        }
    if endpoint.get("volume_identity_required") and not expected:
        return {
            "available": False,
            "reason": "volume_identity_unbound",
            "root": probe["root"],
            "expected_identity": None,
            "current_identity": current,
        }
    if expected and current and expected != current:
        return {
            "available": False,
            "reason": "volume_identity_mismatch",
            "root": probe["root"],
            "expected_identity": expected,
            "current_identity": current,
        }
    return {
        "available": True,
        "reason": None,
        "root": probe["root"],
        "expected_identity": expected,
        "current_identity": current,
    }
