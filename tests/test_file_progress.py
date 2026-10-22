from backend.files.jobs import _measure_source

import threading


def test_measure_source_returns_real_file_and_byte_totals(tmp_path):
    root = tmp_path / "tree"
    root.mkdir()
    (root / "a.bin").write_bytes(b"a" * 11)
    nested = root / "nested"
    nested.mkdir()
    (nested / "b.bin").write_bytes(b"b" * 29)

    files, total_bytes = _measure_source(root, threading.Event())

    assert files == 2
    assert total_bytes == 40
