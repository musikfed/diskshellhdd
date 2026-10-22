from pathlib import Path

from backend.scanner.classifier import classify_path


def test_classifier_handles_media_and_development():
    assert classify_path(Path("D:/Photos/a.CR2"), ".cr2") == "photo"
    assert classify_path(Path("D:/Movies/a.mkv"), ".mkv") == "video"
    assert classify_path(Path("D:/project/node_modules/a.js"), ".js") == "development"
