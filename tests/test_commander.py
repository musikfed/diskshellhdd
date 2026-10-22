from __future__ import annotations

import time
from types import SimpleNamespace

import backend.commander.jobs as commander_jobs
from backend.remote.service import _normalize_remote_path, _public_profile
from backend.storage_brain.service import suggest_managed_destination


def test_remote_public_profile_never_exposes_secrets():
    profile = {
        "id": "abc",
        "protocol": "sftp",
        "host": "example.test",
        "port": 22,
        "username": "user",
        "password": "secret",
        "private_key_path": "C:/secret/key",
        "accept_unknown_host": False,
        "passive": True,
        "tls": False,
        "root": "/",
        "connected_at": "now",
    }

    public = _public_profile(profile)

    assert public["host"] == "example.test"
    assert "password" not in public
    assert "private_key_path" not in public


def test_remote_paths_are_normalized_to_posix_absolute():
    assert _normalize_remote_path("home/user/../data") == "/home/data"
    assert _normalize_remote_path(r"\home\user\file.txt") == "/home/user/file.txt"


def test_commander_local_copy_job_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(
        commander_jobs,
        "settings",
        SimpleNamespace(allow_file_writes=True),
    )
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"x" * (2 * 1024 * 1024))

    job = commander_jobs.start_commander_job(
        "copy",
        {"kind": "local", "path": str(source)},
        {"kind": "local", "path": str(destination)},
    )

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = commander_jobs.get_commander_job(job["id"])
        if job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.02)

    assert job["status"] == "completed"
    assert job["progress_percent"] == 100.0
    assert job["bytes"] == source.stat().st_size
    assert destination.read_bytes() == source.read_bytes()


def test_smart_destination_does_not_create_target_directories(tmp_path):
    storage_root = tmp_path / "Storage"
    storage_root.mkdir()

    result = suggest_managed_destination(
        source_name="photo.jpg",
        source_path=r"F:\chaos\photo.jpg",
        size=123,
        modified_ns=None,
        storage_root=storage_root,
    )

    assert result["target_class"] == "photos"
    assert result["layout_lane"] == "B-photo-mixed"
    assert not (storage_root / "Photos").exists()
