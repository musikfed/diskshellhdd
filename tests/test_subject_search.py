from __future__ import annotations

from pathlib import Path

import backend.core.database as database
import backend.vision.subjects as subjects
from backend.core.database import connect, init_database


def _seed_photo_scan(tmp_path: Path) -> int:
    init_database()
    photo_a = tmp_path / "car.jpg"
    photo_b = tmp_path / "dog.jpg"
    photo_a.write_bytes(b"fake-a")
    photo_b.write_bytes(b"fake-b")
    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO scan_sessions(
                root_path,status,files_count,directories_count,bytes_total,completed_at
            ) VALUES(?, 'completed', 2, 0, 12, CURRENT_TIMESTAMP)
            """,
            (str(tmp_path),),
        )
        scan_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO files(
                scan_id,path,parent_path,name,extension,category,size
            ) VALUES(?,?,?,?,?,'photo',?)
            """,
            [
                (scan_id, str(photo_a), str(tmp_path), photo_a.name, ".jpg", 6),
                (scan_id, str(photo_b), str(tmp_path), photo_b.name, ".jpg", 6),
            ],
        )
        connection.commit()
    return scan_id


def test_subject_index_and_search_are_persistent(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "subjects.db")
    scan_id = _seed_photo_scan(tmp_path)

    monkeypatch.setattr(subjects, "capabilities", lambda: {"ready": True, "cloud": False})
    monkeypatch.setattr(subjects, "_model_key", lambda: "test-model")

    def fake_classify(path, *, top_k=8, min_score=0.03):
        del top_k, min_score
        if str(path).endswith("car.jpg"):
            return [
                {"label": "sports car", "score": 0.91, "class_index": 1},
                {"label": "vehicle", "score": 0.42, "class_index": 2},
            ]
        return [
            {"label": "golden retriever", "score": 0.88, "class_index": 3},
            {"label": "dog", "score": 0.77, "class_index": 4},
        ]

    monkeypatch.setattr(subjects, "classify_image", fake_classify)

    result = subjects.analyze_subjects(scan_id)
    assert result["photos_analyzed"] == 2
    assert result["tags_written"] == 4
    assert result["errors"] == 0

    car = subjects.search_subjects(scan_id, "car")
    assert len(car) == 1
    assert car[0]["path"].endswith("car.jpg")
    assert car[0]["score"] == 0.91

    dog = subjects.search_subjects(scan_id, "dog")
    assert len(dog) == 1
    assert dog[0]["path"].endswith("dog.jpg")

    top = subjects.top_subjects(scan_id)
    labels = {item["label"] for item in top}
    assert {"sports car", "vehicle", "golden retriever", "dog"} <= labels


def test_subject_reanalysis_replaces_same_model_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "subjects.db")
    scan_id = _seed_photo_scan(tmp_path)
    monkeypatch.setattr(subjects, "capabilities", lambda: {"ready": True})
    monkeypatch.setattr(subjects, "_model_key", lambda: "test-model")

    monkeypatch.setattr(
        subjects,
        "classify_image",
        lambda *_args, **_kwargs: [
            {"label": "old tag", "score": 0.7, "class_index": 0}
        ],
    )
    subjects.analyze_subjects(scan_id)

    monkeypatch.setattr(
        subjects,
        "classify_image",
        lambda *_args, **_kwargs: [
            {"label": "new tag", "score": 0.8, "class_index": 1}
        ],
    )
    subjects.analyze_subjects(scan_id)

    assert subjects.search_subjects(scan_id, "old") == []
    assert len(subjects.search_subjects(scan_id, "new")) == 2


def test_subject_capabilities_are_local_only(monkeypatch, tmp_path):
    model = tmp_path / "classifier.onnx"
    labels = tmp_path / "labels.txt"
    model.write_bytes(b"model")
    labels.write_text("cat\ndog\n", encoding="utf-8")
    monkeypatch.setattr(subjects.settings, "image_classifier_model", str(model))
    monkeypatch.setattr(subjects.settings, "image_classifier_labels", str(labels))

    caps = subjects.capabilities()
    assert caps["cloud"] is False
    assert caps["mode"] == "whole_image_classification"
