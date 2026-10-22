from __future__ import annotations

from typing import Any


NTFS_MAX_CLUSTERS = (2**32) - 1
FAT_MAX_CLUSTERS = 65_526
FAT32_MAX_CLUSTERS = 4_177_917
FAT_MAX_FILE_BYTES = (4 * 1024**3) - 1


FILESYSTEM_PROFILES: dict[str, dict[str, Any]] = {
    "NTFS": {
        "title": "NTFS",
        "clusters": [
            512,
            1024,
            2048,
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
        "max_clusters": NTFS_MAX_CLUSTERS,
        "warning": (
            "Основная Windows FS: журнал, ACL, ADS. 4 KiB — универсально; "
            "16 KiB — хороший mixed-large-storage профиль; 64 KiB — крупные "
            "последовательные данные. NTFS compression не работает выше 4 KiB."
        ),
    },
    "EXFAT": {
        "title": "exFAT",
        "clusters": [
            512,
            1024,
            2048,
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
            "Переносимая FS для Windows/Linux/macOS и больших файлов. "
            "Не имеет набора NTFS ACL/journal/ADS; для постоянно подключённого "
            "Windows storage обычно предпочтительнее NTFS."
        ),
    },
    "REFS": {
        "title": "ReFS",
        "clusters": [4096, 65536],
        "recommended_cluster": 65536,
        "family": "windows_advanced",
        "warning": (
            "Resilient File System. Доступность форматирования зависит от edition/build "
            "Windows и сценария; DiskShell попросит Windows подтвердить поддержку."
        ),
    },
    "FAT32": {
        "title": "FAT32",
        "clusters": [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536],
        "recommended_cluster": 32768,
        "family": "legacy",
        "max_clusters": FAT32_MAX_CLUSTERS,
        "max_file_bytes": FAT_MAX_FILE_BYTES,
        "warning": (
            "Legacy compatibility. Один файл не может быть больше 4 GiB−1; "
            "максимальный размер тома зависит от cluster size. Не подходит как "
            "основная FS для 4-TB media/storage."
        ),
    },
    "FAT": {
        "title": "FAT",
        "clusters": [512, 1024, 2048, 4096, 8192, 16384, 32768, 65536],
        "recommended_cluster": 4096,
        "family": "legacy",
        "max_clusters": FAT_MAX_CLUSTERS,
        "max_file_bytes": FAT_MAX_FILE_BYTES,
        "warning": (
            "Старая FAT (обычно FAT16). Только для небольших legacy-томов; "
            "для современного HDD почти никогда не нужна."
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


def max_volume_bytes(filesystem: str, allocation_unit: int) -> int | None:
    profile = filesystem_profile(filesystem)
    max_clusters = profile.get("max_clusters")
    if max_clusters is None:
        return None
    return int(max_clusters) * int(allocation_unit)


def validate_volume_size(
    filesystem: str,
    allocation_unit: int,
    volume_size: int,
) -> int:
    size = int(volume_size)
    if size <= 0:
        raise ValueError("Volume size must be greater than zero")
    limit = max_volume_bytes(filesystem, allocation_unit)
    if limit is not None and size > limit:
        raise ValueError(
            f"{filesystem} with allocation unit {allocation_unit} B supports at most "
            f"{limit} bytes with the configured cluster-count limit; choose a larger "
            "allocation unit or a different filesystem"
        )
    return size


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
                "max_file_bytes": profile.get("max_file_bytes"),
            }
            for key, profile in FILESYSTEM_PROFILES.items()
        ]
    }
