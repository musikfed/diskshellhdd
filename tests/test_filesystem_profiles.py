import pytest

from backend.services.storage.filesystem_profiles import (
    capabilities,
    max_volume_bytes,
    validate_volume_size,
)


def test_format_volume_filesystems_are_exposed():
    keys = {item["key"] for item in capabilities()["filesystems"]}
    assert {"NTFS", "EXFAT", "REFS", "FAT32", "FAT"} <= keys


def test_ntfs_cluster_limit_rejects_oversized_volume():
    limit = max_volume_bytes("NTFS", 512)
    assert limit is not None

    with pytest.raises(ValueError, match="choose a larger allocation unit"):
        validate_volume_size("NTFS", 512, limit + 1)

    assert validate_volume_size("NTFS", 16384, 4_000_000_000_000) == 4_000_000_000_000


def test_fat32_cluster_count_limit_is_enforced():
    limit = max_volume_bytes("FAT32", 32768)
    assert limit is not None

    with pytest.raises(ValueError):
        validate_volume_size("FAT32", 32768, limit + 1)
