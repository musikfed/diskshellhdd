from __future__ import annotations

import time

import backend.streamcopy.jobs as streamcopy_jobs


def _wait(job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    job = streamcopy_jobs.get_streamcopy_job(job_id)
    while time.monotonic() < deadline:
        job = streamcopy_jobs.get_streamcopy_job(job_id)
        if job["status"] in {"completed", "completed_with_warnings", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    return job


def test_hdd_usb3_profile_uses_manual_media_and_cache_hints():
    profile = streamcopy_jobs.stream_profile(
        "hdd",
        "hdd",
        "usb3",
        "usb3",
        "unknown",
        32,
        128,
    )

    assert profile["strategy"] == "hdd-hdd-sequential-pipeline"
    assert profile["source_media"] == "hdd"
    assert profile["destination_media"] == "hdd"
    assert profile["chunk_mib"] == 8
    assert profile["queue_depth"] == 6
    assert profile["max_buffer_mib"] == 48
    assert profile["source_cache_mib"] == 32
    assert profile["destination_cache_mib"] == 128


def test_hdd_usb3_shared_path_reduces_queue_depth():
    profile = streamcopy_jobs.stream_profile(
        "hdd",
        "hdd",
        "usb3",
        "usb3",
        "shared",
        32,
        128,
    )

    assert profile["strategy"] == "hdd-hdd-sequential-pipeline"
    assert profile["queue_depth"] == 4
    assert profile["max_buffer_mib"] == 32


def test_streamcopy_directory_keeps_structure_and_contents(tmp_path, monkeypatch):
    monkeypatch.setattr(streamcopy_jobs, "file_writes_allowed", lambda: True)

    source = tmp_path / "source"
    source.mkdir()
    (source / "tiny.txt").write_bytes(b"tiny")
    nested = source / "nested"
    nested.mkdir()
    (nested / "large.bin").write_bytes(b"x" * (2 * 1024 * 1024))

    destination = tmp_path / "destination"
    job = streamcopy_jobs.start_streamcopy_job(
        str(source),
        str(destination),
        "hdd",
        "hdd",
        "usb3",
        "usb3",
        "unknown",
        32,
        128,
    )
    job = _wait(job["id"])

    assert job["status"] == "completed"
    assert job["files"] == 2
    assert job["total_files"] == 2
    assert job["bytes"] == job["total_bytes"]
    assert job["profile"]["strategy"] == "hdd-hdd-sequential-pipeline"
    assert (destination / "source" / "tiny.txt").read_bytes() == b"tiny"
    assert (destination / "source" / "nested" / "large.bin").read_bytes() == b"x" * (
        2 * 1024 * 1024
    )


def test_streamcopy_existing_destination_is_skipped_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(streamcopy_jobs, "file_writes_allowed", lambda: True)

    source = tmp_path / "source"
    source.mkdir()
    (source / "keep.txt").write_bytes(b"new")

    destination = tmp_path / "destination"
    target_root = destination / "source"
    target_root.mkdir(parents=True)
    target = target_root / "keep.txt"
    target.write_bytes(b"old")

    job = streamcopy_jobs.start_streamcopy_job(
        str(source),
        str(destination),
        "hdd",
        "hdd",
        "usb3",
        "usb3",
        "unknown",
        32,
        128,
    )
    job = _wait(job["id"])

    assert job["status"] == "completed_with_warnings"
    assert job["skipped"] == 1
    assert target.read_bytes() == b"old"
