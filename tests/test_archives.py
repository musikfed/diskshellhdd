from __future__ import annotations

import backend.archives.service as archives


def test_zip_create_list_and_extract(tmp_path, monkeypatch):
    monkeypatch.setattr(archives, "file_writes_allowed", lambda: True)

    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("hello", encoding="utf-8")
    (source / "b.bin").write_bytes(b"x" * 1024)

    target = tmp_path / "bundle.zip"
    result = archives.create_archive([source], target, "zip")

    assert result["status"] == "completed"
    assert result["files"] == 2

    listing = archives.list_archive(target)
    names = {item["name"] for item in listing["entries"]}
    assert "source/a.txt" in names
    assert "source/b.bin" in names

    extracted = tmp_path / "extracted"
    extract_result = archives.extract_archive(target, extracted)

    assert extract_result["files"] == 2
    assert (extracted / "source" / "a.txt").read_text(encoding="utf-8") == "hello"
