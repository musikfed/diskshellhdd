from __future__ import annotations

import io
import threading
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
    )

    assert bytes(store["data"]) == payload
    assert sum(progress) == len(payload)
    assert offsets == [0, 4]
    assert len(retries) == 1
