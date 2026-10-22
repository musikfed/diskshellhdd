from __future__ import annotations

from typing import Any


FILESYSTEM_PROFILES: dict[str, dict[str, Any]] = {
    "NTFS": {
        "title": "NTFS",
        "clusters": [
            4096,
            8192,
            16384,
            32768,
            65536,
            131072,
            262144,
            524288,
            1048576,
            2097152,
        ],
        "recommended_cluster": 16384,
        "family": "windows_native",
        "warning": (
            "Best general Windows choice. 4 KiB is universal, 16 KiB suits mixed "
            "large-file storage, 64 KiB suits mostly large sequential files. "
            "Clusters above 64 KiB are advanced."
        ),
    },
    "EXFAT": {
        "title": "exFAT",
        "clusters": [
            4096,
            8192,
            16384,
            32768,
            65536,
            131072,
            262144,
            524288,
            1048576,
            2097152,
            4194304,
            8388608,
            16777216,
            33554432,
        ],
        "recommended_cluster": 131072,
        "family": "portable",
        "warning": (
            "Portable large-volume filesystem. No NTFS journal, ACL feature set, "
            "or alternate data streams; use when interoperability matters."
        ),
    },
    "REFS": {
        "title": "ReFS",
        "clusters": [4096, 65536],
        "recommended_cluster": 65536,
        "family": "windows_advanced",
        "warning": (
            "Advanced resilient filesystem. Formatting availability depends on "
            "the installed Windows edition/build and target media; Windows may "
            "reject the operation even when the cmdlet exposes ReFS."
        ),
    },
    "FAT32": {
        "title": "FAT32",
        "clusters": [4096, 8192, 16384, 32768, 65536],
        "recommended_cluster": 32768,
        "family": "legacy",
        "warning": (
            "Legacy compatibility filesystem with a 4 GiB maximum individual file "
            "size. Not recommended for a multi-terabyte storage volume."
        ),
    },
}


def filesystem_names() -> set[str]:
    return set(FILESYSTEM_PROFILES)


def filesystem_profile(filesystem: str) -> dict[str, Any]:
    key = str(filesystem).upper()
    try:
        return FILESYSTEM_PROFILES[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported filesystem: {filesystem}") from exc


def validate_allocation_unit(filesystem: str, allocation_unit: int) -> int:
    profile = filesystem_profile(filesystem)
    value = int(allocation_unit)
    if value not in profile["clusters"]:
        allowed = ", ".join(str(item) for item in profile["clusters"])
        raise ValueError(
            f"Unsupported allocation unit size for {filesystem}: {value}; allowed: {allowed}"
        )
    return value


def capabilities() -> dict[str, Any]:
    return {
        "filesystems": [
            {
                "key": key,
                "title": profile["title"],
                "clusters": list(profile["clusters"]),
                "recommended_cluster": profile["recommended_cluster"],
                "family": profile["family"],
                "warning": profile["warning"],
            }
            for key, profile in FILESYSTEM_PROFILES.items()
        ]
    }
