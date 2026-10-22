from __future__ import annotations

import io
import threading
import time
from types import SimpleNamespace
import backend.commander.jobs as commander_jobs
import backend.files.endpoint_availability as endpoint_availability
from backend.remote.service import (
    RemoteConnectionError,
    RemoteNotFound,
    SFTPSession,
    _normalize_remote_path,
    _public_profile,
)
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
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
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


def test_commander_batch_copy_reports_items_and_total_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    source_a = tmp_path / "a.bin"
    source_b = tmp_path / "b.bin"
    destination = tmp_path / "target"
    destination.mkdir()
    source_a.write_bytes(b"a" * 1024)
    source_b.write_bytes(b"b" * 2048)

    job = commander_jobs.start_commander_batch_job(
        "copy",
        [
            {
                "source": {"kind": "local", "path": str(source_a)},
                "destination": {
                    "kind": "local",
                    "path": str(destination / source_a.name),
                },
            },
            {
                "source": {"kind": "local", "path": str(source_b)},
                "destination": {
                    "kind": "local",
                    "path": str(destination / source_b.name),
                },
            },
        ],
    )

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = commander_jobs.get_commander_job(job["id"])
        if job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.02)

    assert job["status"] == "completed"
    assert job["type"] == "commander_transfer_batch"
    assert job["items"] == 2
    assert job["total_items"] == 2
    assert job["files"] == 2
    assert job["total_files"] == 2
    assert job["bytes"] == 3072
    assert job["total_bytes"] == 3072
    assert job["progress_percent"] == 100.0
    assert (destination / "a.bin").read_bytes() == source_a.read_bytes()
    assert (destination / "b.bin").read_bytes() == source_b.read_bytes()



class _FakeRemoteSession:
    def __init__(self, *, reader_factory=None, remote_store=None, fail_upload_once=None, offsets=None):
        self.reader_factory = reader_factory
        self.remote_store = remote_store
        self.fail_upload_once = fail_upload_once
        self.offsets = offsets if offsets is not None else []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def stat(self, _path):
        if self.remote_store is None or not self.remote_store["exists"]:
            raise commander_jobs.RemoteNotFound(_path)
        return SimpleNamespace(is_dir=False, size=len(self.remote_store["data"]))

    def makedirs(self, _path):
        return None

    def open_read(self, _path, offset=0):
        self.offsets.append(offset)
        return self.reader_factory(offset)

    def open_write(self, _path, offset=0):
        self.offsets.append(offset)
        self.remote_store["exists"] = True
        return _FakeRemoteWriter(
            self.remote_store["data"],
            offset,
            self.fail_upload_once,
        )


class _FlakyRemoteReader(io.BytesIO):
    def __init__(self, payload, offset, fail_once):
        super().__init__(payload)
        self.seek(offset)
        self.fail_once = fail_once

    def read(self, size=-1):
        if self.fail_once["value"] and self.tell() >= 4:
            self.fail_once["value"] = False
            raise ConnectionResetError("simulated SSH drop")
        return super().read(size)


class _FakeRemoteWriter(io.RawIOBase):
    def __init__(self, store, offset, fail_once):
        self.store = store
        self.position = offset
        self.fail_once = fail_once
        self._closed = False

    def writable(self):
        return True

    def write(self, data):
        if self.fail_once["value"] and self.position >= 4:
            self.fail_once["value"] = False
            raise ConnectionResetError("simulated SSH drop")
        end = self.position + len(data)
        if end > len(self.store):
            self.store.extend(b"\0" * (end - len(self.store)))
        self.store[self.position:end] = data
        self.position = end
        return len(data)

    def flush(self):
        return None

    @property
    def closed(self):
        return self._closed

    def close(self):
        self._closed = True


def test_commander_remote_download_reconnects_and_resumes(tmp_path, monkeypatch):
    payload = b"abcdefghijkl"
    fail_once = {"value": True}
    offsets = []

    def open_fake_session(_connection_id):
        return _FakeRemoteSession(
            reader_factory=lambda offset: _FlakyRemoteReader(
                payload,
                offset,
                fail_once,
            ),
            offsets=offsets,
        )

    monkeypatch.setattr(commander_jobs, "open_session", open_fake_session)
    monkeypatch.setattr(commander_jobs, "CHUNK_SIZE", 4)
    monkeypatch.setattr(
        commander_jobs,
        "TRANSFER_RETRY_BACKOFF_SECONDS",
        (0.0, 0.0, 0.0, 0.0),
    )

    destination = tmp_path / "download.bin"
    progress = []
    retries = []

    commander_jobs._copy_file(
        {"kind": "remote", "connection_id": "ssh-1", "path": "/large.bin"},
        {"kind": "local", "path": str(destination)},
        len(payload),
        threading.Event(),
        lambda count, _path: progress.append(count),
        lambda *args: retries.append(args),
        lambda *_args: None,
    )

    assert destination.read_bytes() == payload
    assert sum(progress) == len(payload)
    assert offsets == [0, 4]
    assert len(retries) == 1


def test_commander_remote_upload_reconnects_and_resumes(tmp_path, monkeypatch):
    payload = b"abcdefghijkl"
    source = tmp_path / "upload.bin"
    source.write_bytes(payload)
    store = {"exists": False, "data": bytearray()}
    fail_once = {"value": True}
    offsets = []

    def open_fake_session(_connection_id):
        return _FakeRemoteSession(
            remote_store=store,
            fail_upload_once=fail_once,
            offsets=offsets,
        )

    monkeypatch.setattr(commander_jobs, "open_session", open_fake_session)
    monkeypatch.setattr(commander_jobs, "CHUNK_SIZE", 4)
    monkeypatch.setattr(
        commander_jobs,
        "TRANSFER_RETRY_BACKOFF_SECONDS",
        (0.0, 0.0, 0.0, 0.0),
    )

    progress = []
    retries = []

    commander_jobs._copy_file(
        {"kind": "local", "path": str(source)},
        {"kind": "remote", "connection_id": "ssh-1", "path": "/large.bin"},
        len(payload),
        threading.Event(),
        lambda count, _path: progress.append(count),
        lambda *args: retries.append(args),
        lambda *_args: None,
    )

    assert bytes(store["data"]) == payload
    assert sum(progress) == len(payload)
    assert offsets == [0, 4]
    assert len(retries) == 1



def test_commander_cross_volume_move_preserves_zero_byte_files(tmp_path, monkeypatch):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    monkeypatch.setattr(commander_jobs, "_same_native_location", lambda _src, _dst: False)

    source = tmp_path / "source-tree"
    source.mkdir()
    (source / ".python-version").write_text("3.12\n", encoding="utf-8")
    (source / "README.md").write_bytes(b"")
    nested = source / "nested"
    nested.mkdir()
    (nested / "empty.txt").write_bytes(b"")
    (nested / "data.bin").write_bytes(b"abc")

    destination = tmp_path / "destination-tree"
    job = commander_jobs.start_commander_job(
        "move",
        {"kind": "local", "path": str(source)},
        {"kind": "local", "path": str(destination)},
    )

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = commander_jobs.get_commander_job(job["id"])
        if job["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.02)

    assert job["status"] == "completed", job["error"]
    assert not source.exists()
    assert (destination / ".python-version").read_text(encoding="utf-8") == "3.12\n"
    assert (destination / "README.md").exists()
    assert (destination / "README.md").stat().st_size == 0
    assert (destination / "nested" / "empty.txt").exists()
    assert (destination / "nested" / "empty.txt").stat().st_size == 0
    assert (destination / "nested" / "data.bin").read_bytes() == b"abc"


def test_zero_byte_copy_updates_current_path_before_verify(tmp_path, monkeypatch):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    monkeypatch.setattr(commander_jobs, "_same_native_location", lambda _src, _dst: False)

    source = tmp_path / "source-tree"
    source.mkdir()
    (source / "a.txt").write_bytes(b"x")
    (source / "z-empty.txt").write_bytes(b"")
    destination = tmp_path / "destination-tree"

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

    assert job["status"] == "completed", job["error"]
    assert job["current_path"].endswith("z-empty.txt")
    assert (destination / "z-empty.txt").exists()



def _wait_commander_job(job_id, timeout=5):
    deadline = time.monotonic() + timeout
    job = commander_jobs.get_commander_job(job_id)
    while time.monotonic() < deadline:
        job = commander_jobs.get_commander_job(job_id)
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    return job


def test_commander_missing_selected_source_is_skipped_not_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    missing = tmp_path / "already-gone.txt"
    destination = tmp_path / "copied.txt"

    job = commander_jobs.start_commander_job(
        "copy",
        {"kind": "local", "path": str(missing)},
        {"kind": "local", "path": str(destination)},
    )
    job = _wait_commander_job(job["id"])

    assert job["status"] == "completed"
    assert job["missing"] == 1
    assert job["skipped"] == 1
    assert job["items"] == 1
    assert not destination.exists()
    assert any("Source missing" in item for item in job["warnings"])


def test_commander_conflict_requires_explicit_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"abcdefgh")
    destination.write_bytes(b"abcd")

    try:
        commander_jobs.start_commander_job(
            "copy",
            {"kind": "local", "path": str(source)},
            {"kind": "local", "path": str(destination)},
        )
    except commander_jobs.CommanderConflict as exc:
        assert len(exc.conflicts) == 1
        assert exc.conflicts[0]["can_resume"] is True
        assert exc.conflicts[0]["destination_size"] == 4
    else:
        raise AssertionError("Expected CommanderConflict")


def test_commander_resume_existing_partial_local_file(tmp_path, monkeypatch):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    monkeypatch.setattr(commander_jobs, "_same_native_location", lambda _src, _dst: False)
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"abcdefghijkl")
    destination.write_bytes(b"abcd")

    job = commander_jobs.start_commander_job(
        "copy",
        {"kind": "local", "path": str(source)},
        {"kind": "local", "path": str(destination)},
        conflict_policy="resume",
    )
    job = _wait_commander_job(job["id"])

    assert job["status"] == "completed", job["error"]
    assert destination.read_bytes() == source.read_bytes()
    assert job["bytes"] == len(source.read_bytes())


def test_commander_keep_both_adds_incremented_name(tmp_path, monkeypatch):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    monkeypatch.setattr(commander_jobs, "_same_native_location", lambda _src, _dst: False)
    source = tmp_path / "report.txt"
    destination = tmp_path / "target" / "report.txt"
    destination.parent.mkdir()
    source.write_text("new", encoding="utf-8")
    destination.write_text("old", encoding="utf-8")
    (destination.parent / "report (1).txt").write_text("older", encoding="utf-8")

    job = commander_jobs.start_commander_job(
        "copy",
        {"kind": "local", "path": str(source)},
        {"kind": "local", "path": str(destination)},
        conflict_policy="keep_both",
    )
    job = _wait_commander_job(job["id"])

    assert job["status"] == "completed", job["error"]
    assert destination.read_text(encoding="utf-8") == "old"
    assert (destination.parent / "report (1).txt").read_text(encoding="utf-8") == "older"
    assert (destination.parent / "report (2).txt").read_text(encoding="utf-8") == "new"
    assert job["transfers"][0]["conflict_resolution"] == "keep_both"
    assert job["transfers"][0]["destination"]["path"].endswith("report (2).txt")


def test_commander_replace_overwrites_only_after_source_recheck(tmp_path, monkeypatch):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    monkeypatch.setattr(commander_jobs, "_same_native_location", lambda _src, _dst: False)
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"new-content")
    destination.write_bytes(b"old-content")

    job = commander_jobs.start_commander_job(
        "copy",
        {"kind": "local", "path": str(source)},
        {"kind": "local", "path": str(destination)},
        conflict_policy="replace",
    )
    job = _wait_commander_job(job["id"])

    assert job["status"] == "completed", job["error"]
    assert destination.read_bytes() == b"new-content"


def test_commander_replace_does_not_delete_target_if_source_disappears(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"new-content")
    destination.write_bytes(b"old-content")

    original_source_exists = commander_jobs._source_exists
    calls = {"count": 0}

    def disappears_after_prepare(endpoint):
        if endpoint["path"] == str(source):
            calls["count"] += 1
            if calls["count"] == 1:
                source.unlink()
                return False
        return original_source_exists(endpoint)

    monkeypatch.setattr(commander_jobs, "_source_exists", disappears_after_prepare)

    job = commander_jobs.start_commander_job(
        "copy",
        {"kind": "local", "path": str(source)},
        {"kind": "local", "path": str(destination)},
        conflict_policy="replace",
    )
    job = _wait_commander_job(job["id"])

    assert job["status"] == "completed"
    assert job["missing"] == 1
    assert destination.read_bytes() == b"old-content"


def test_commander_cancel_retains_partial_target_for_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    monkeypatch.setattr(commander_jobs, "_same_native_location", lambda _src, _dst: False)
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"abcdefghijkl")

    original_copy_file = commander_jobs._copy_file

    def interrupted_copy(
        source_ep,
        destination_ep,
        expected_size,
        event,
        progress,
        retry_status,
        wait_status,
    ):
        del expected_size, event, retry_status, wait_status
        target = commander_jobs._local_path(destination_ep)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"abcd")
        progress(4, source_ep["path"])
        raise commander_jobs.CommanderCancelled("simulated Stop")

    monkeypatch.setattr(commander_jobs, "_copy_file", interrupted_copy)
    job = commander_jobs.start_commander_job(
        "copy",
        {"kind": "local", "path": str(source)},
        {"kind": "local", "path": str(destination)},
    )
    job = _wait_commander_job(job["id"])
    monkeypatch.setattr(commander_jobs, "_copy_file", original_copy_file)

    assert job["status"] == "cancelled"
    assert job["partial_retained"] is True
    assert job["partial_path"] == str(destination)
    assert destination.read_bytes() == b"abcd"



class _StatFailureSFTP:
    def __init__(self, exc):
        self.exc = exc

    def stat(self, _path):
        raise self.exc


def test_sftp_stat_only_treats_enoent_as_missing():
    missing = SFTPSession({})
    missing.sftp = _StatFailureSFTP(OSError(2, "No such file"))
    try:
        missing.stat("/gone.txt")
    except RemoteNotFound:
        pass
    else:
        raise AssertionError("ENOENT must map to RemoteNotFound")

    broken = SFTPSession({})
    broken.sftp = _StatFailureSFTP(OSError(5, "I/O transport error"))
    try:
        broken.stat("/maybe-there.txt")
    except RemoteConnectionError:
        pass
    else:
        raise AssertionError("transport errors must not be reported as missing")



def test_local_volume_identity_mismatch_blocks_auto_resume(monkeypatch):
    monkeypatch.setattr(
        endpoint_availability,
        "local_volume_probe",
        lambda _path: {
            "root": "W:\\",
            "available": True,
            "identity": "volume-new",
        },
    )

    state = endpoint_availability.local_endpoint_state(
        {
            "kind": "local",
            "path": r"W:\\target\\large.bin",
            "volume_identity": "volume-original",
        }
    )

    assert state["available"] is False
    assert state["reason"] == "volume_identity_mismatch"
    assert state["expected_identity"] == "volume-original"
    assert state["current_identity"] == "volume-new"


def test_commander_waits_for_offline_endpoint_then_auto_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(commander_jobs, "file_writes_allowed", lambda: True)
    monkeypatch.setattr(commander_jobs, "ENDPOINT_RECHECK_SECONDS", 0.01)

    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    payload = b"resumable-data" * 1024
    source.write_bytes(payload)

    calls = {"destination": 0}

    def endpoint_state(endpoint, connect_remote=True):
        del connect_remote
        if endpoint["path"] == str(destination):
            calls["destination"] += 1
            if calls["destination"] <= 2:
                return {
                    "available": False,
                    "reason": "volume_offline",
                    "root": str(tmp_path),
                    "expected_identity": "volume-a",
                    "current_identity": None,
                }
        return {
            "available": True,
            "reason": None,
            "root": str(tmp_path),
            "expected_identity": endpoint.get("volume_identity"),
            "current_identity": endpoint.get("volume_identity"),
        }

    monkeypatch.setattr(commander_jobs, "_endpoint_state", endpoint_state)

    job = commander_jobs.start_commander_job(
        "copy",
        {"kind": "local", "path": str(source)},
        {"kind": "local", "path": str(destination)},
    )
    job = _wait_commander_job(job["id"])

    assert job["status"] == "completed", job["error"]
    assert job["wait_cycles"] >= 1
    assert job["auto_resumes"] >= 1
    assert job["waiting_endpoint"] is False
    assert destination.read_bytes() == payload


def test_windows_path_not_found_is_treated_as_endpoint_loss():
    class WindowsPathGone(FileNotFoundError):
        winerror = 3

    assert commander_jobs._looks_like_endpoint_loss(
        WindowsPathGone("device disappeared")
    ) is True
