from __future__ import annotations

import threading

import pytest

from backend.files.jobs import FileOperationCancelled, _copy_file


def test_cancelled_file_copy_removes_partial_target(tmp_path):
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"x" * 1024)

    event = threading.Event()
    event.set()

    with pytest.raises(FileOperationCancelled):
        _copy_file("unused-job", source, destination, event)

    assert source.exists()
    assert not destination.exists()
    assert not list(tmp_path.glob(".*.diskshell-partial-*"))
