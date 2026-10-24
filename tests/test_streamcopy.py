from __future__ import annotations

import hashlib
import threading
import time

import pytest

import backend.core.database as database
import backend.streamcopy.jobs as streamcopy_jobs
from backend.streamcopy import journal


@pytest.fixture(autouse=True)
def isolated_streamcopy_state(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "streamcopy-test.db")
    with streamcopy_jobs._lock:
        streamcopy_jobs._jobs.clear()
        streamcopy_jobs._cancel_events.clear()
        streamcopy_jobs._threads.clear()
    yield
    with streamcopy_jobs._lock:
        events = list(streamcopy_jobs._cancel_events.values())
    for event in events:
        event.set()


def _wait(job_id: str, timeout: float = 8.0) -> dict:
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
    assert profile["checkpoint_mib"] == 128
    assert profile["microfile_batching"] is True
    assert profile["microfile_max_bytes"] == 1024 * 1024
    assert profile["micro_frame_mib"] == 8


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
    (source / "empty").mkdir()

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
    assert job["persistent"] is True
    assert job["recovery_mode"] == "rollback_to_verified_checkpoint"
    assert (destination / "source" / "tiny.txt").read_bytes() == b"tiny"
    assert (destination / "source" / "nested" / "large.bin").read_bytes() == b"x" * (
        2 * 1024 * 1024
    )
    assert (destination / "source" / "empty").is_dir()


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
    assert job["skipped"] >= 1
    assert target.read_bytes() == b"old"


def test_streamcopy_rejects_copying_directory_into_its_own_parent(tmp_path, monkeypatch):
    monkeypatch.setattr(streamcopy_jobs, "file_writes_allowed", lambda: True)
    source = tmp_path / "source"
    source.mkdir()

    with pytest.raises(ValueError, match="source itself"):
        streamcopy_jobs.start_streamcopy_job(
            str(source),
            str(tmp_path),
            "hdd",
            "hdd",
        )


def test_streamcopy_job_survives_loss_of_ram_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(streamcopy_jobs, "file_writes_allowed", lambda: True)
    source = tmp_path / "source.bin"
    source.write_bytes(b"persistent-river")
    destination = tmp_path / "destination"

    job = streamcopy_jobs.start_streamcopy_job(
        str(source),
        str(destination),
        "hdd",
        "hdd",
    )
    job = _wait(job["id"])
    assert job["status"] == "completed"

    with streamcopy_jobs._lock:
        streamcopy_jobs._jobs.clear()

    restored = streamcopy_jobs.get_streamcopy_job(job["id"])
    assert restored["status"] == "completed"
    assert restored["source_path"] == str(source)
    assert restored["destination_path"] == str(destination)
    assert restored["persistent"] is True


def test_recovery_manager_claims_persisted_unfinished_job(tmp_path, monkeypatch):
    monkeypatch.setattr(streamcopy_jobs, "file_writes_allowed", lambda: True)
    source = tmp_path / "source.bin"
    source.write_bytes(b"restart-recovery")
    destination = tmp_path / "destination"

    real_spawn = streamcopy_jobs._spawn_claimed_job
    monkeypatch.setattr(streamcopy_jobs, "_spawn_claimed_job", lambda _job_id: False)
    job = streamcopy_jobs.start_streamcopy_job(
        str(source),
        str(destination),
        "hdd",
        "hdd",
    )
    assert job["status"] == "planning"

    journal.release_lease(job["id"], streamcopy_jobs._INSTANCE_ID)
    monkeypatch.setattr(streamcopy_jobs, "_spawn_claimed_job", real_spawn)

    assert streamcopy_jobs.recover_streamcopy_jobs_once() == 1
    recovered = _wait(job["id"])
    assert recovered["status"] == "completed"
    assert (destination / source.name).read_bytes() == b"restart-recovery"


def test_river_keeper_rolls_partial_tail_back_to_verified_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(streamcopy_jobs, "file_writes_allowed", lambda: True)
    source = tmp_path / "source.bin"
    block = b"A" * (1024 * 1024)
    tail = b"B" * (256 * 1024)
    source.write_bytes(block + tail)
    destination = tmp_path / "destination"

    real_spawn = streamcopy_jobs._spawn_claimed_job
    monkeypatch.setattr(streamcopy_jobs, "_spawn_claimed_job", lambda _job_id: False)
    job = streamcopy_jobs.start_streamcopy_job(
        str(source),
        str(destination),
        "hdd",
        "hdd",
    )
    streamcopy_jobs._build_manifest(job["id"], source, destination)
    item = journal.list_items(job["id"])[0]

    partial = tmp_path / "destination" / (source.name + f".dspart-{job['id'][:12]}")
    partial.parent.mkdir(parents=True, exist_ok=True)
    partial.write_bytes(block + b"CORRUPT-TAIL")

    digest = hashlib.sha256(block).hexdigest()
    journal.add_checkpoint(
        job["id"],
        0,
        offset=len(block),
        block_start=0,
        block_size=len(block),
        digest=digest,
    )

    offset = streamcopy_jobs._safe_resume_offset(
        job["id"],
        item,
        cancel=threading.Event(),
        lease_lost=threading.Event(),
    )
    assert offset == len(block)
    assert partial.stat().st_size == len(block)
    assert partial.read_bytes() == block

    journal.release_lease(job["id"], streamcopy_jobs._INSTANCE_ID)
    monkeypatch.setattr(streamcopy_jobs, "_spawn_claimed_job", real_spawn)


def test_copy_then_delete_forces_sha256_and_removes_source_after_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(streamcopy_jobs, "file_writes_allowed", lambda: True)
    source = tmp_path / "source.bin"
    payload = b"copy-verify-delete"
    source.write_bytes(payload)
    destination = tmp_path / "destination"

    job = streamcopy_jobs.start_streamcopy_job(
        str(source),
        str(destination),
        "hdd",
        "hdd",
        verify_mode="size",
        delete_source_after_verify=True,
    )
    assert job["verify_mode"] == "sha256"
    assert job["operation"] == "copy_then_delete"

    job = _wait(job["id"])
    assert job["status"] == "completed"
    assert not source.exists()
    assert (destination / "source.bin").read_bytes() == payload



def test_streamcopy_microfiles_use_shared_frames(tmp_path, monkeypatch):
    monkeypatch.setattr(streamcopy_jobs, "file_writes_allowed", lambda: True)

    source = tmp_path / "micro-source"
    source.mkdir()
    expected = {}
    for index in range(24):
        payload = (f"file-{index:02d}-".encode("utf-8") * 128)
        path = source / f"small-{index:02d}.bin"
        path.write_bytes(payload)
        expected[path.name] = payload

    destination = tmp_path / "destination"
    calls = []
    original = streamcopy_jobs._copy_micro_batch

    def wrapped(job_id, batch, cancel, lease_lost):
        calls.append(len(batch))
        return original(job_id, batch, cancel, lease_lost)

    monkeypatch.setattr(streamcopy_jobs, "_copy_micro_batch", wrapped)

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

    assert job["status"] == "completed", job["error"]
    assert calls
    assert max(calls) >= 2
    assert job["files"] == len(expected)
    assert job["bytes"] == job["total_bytes"]
    assert job["average_scope"] == "current transfer session; manifest scan excluded"
    for name, payload in expected.items():
        assert (destination / source.name / name).read_bytes() == payload


def test_microbatch_skips_recovery_item_with_existing_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(streamcopy_jobs, "file_writes_allowed", lambda: True)

    source = tmp_path / "source"
    source.mkdir()
    first = source / "a.bin"
    second = source / "b.bin"
    first.write_bytes(b"A" * 1024)
    second.write_bytes(b"B" * 1024)
    destination = tmp_path / "destination"

    real_spawn = streamcopy_jobs._spawn_claimed_job
    monkeypatch.setattr(streamcopy_jobs, "_spawn_claimed_job", lambda _job_id: False)
    job = streamcopy_jobs.start_streamcopy_job(
        str(source),
        str(destination),
        "hdd",
        "hdd",
    )
    streamcopy_jobs._build_manifest(job["id"], source, destination)
    items = journal.list_items(job["id"])

    partial = items[0]["partial_path"]
    from pathlib import Path
    partial_path = Path(partial)
    partial_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path.write_bytes(b"A" * 512)

    candidates = streamcopy_jobs._micro_batch_candidates(
        job["id"],
        items,
        0,
        streamcopy_jobs.MICRO_FILE_MAX_BYTES,
    )
    assert candidates == []

    journal.release_lease(job["id"], streamcopy_jobs._INSTANCE_ID)
    monkeypatch.setattr(streamcopy_jobs, "_spawn_claimed_job", real_spawn)
