from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from backend.config import settings
from backend.core.database import connect, init_database


class SubjectEngineUnavailable(RuntimeError):
    pass


_session_cache: dict[str, Any] = {}
_labels_cache: dict[str, list[str]] = {}


def _model_path() -> Path | None:
    return Path(settings.image_classifier_model).expanduser() if settings.image_classifier_model else None


def _labels_path() -> Path | None:
    return Path(settings.image_classifier_labels).expanduser() if settings.image_classifier_labels else None


def _load_labels(path: Path) -> list[str]:
    key = str(path.resolve())
    cached = _labels_cache.get(key)
    if cached is not None:
        return cached
    raw = path.read_text(encoding="utf-8-sig").strip()
    if raw.startswith("["):
        parsed = json.loads(raw)
        labels = [str(item).strip() for item in parsed if str(item).strip()]
    else:
        labels = []
        for line in raw.splitlines():
            value = line.strip()
            if not value:
                continue
            # Accept "0 cat" / "0,cat" / plain "cat".
            if "," in value and value.split(",", 1)[0].strip().isdigit():
                value = value.split(",", 1)[1].strip()
            elif " " in value and value.split(" ", 1)[0].strip().isdigit():
                value = value.split(" ", 1)[1].strip()
            labels.append(value)
    if not labels:
        raise ValueError("Classifier labels file is empty")
    _labels_cache[key] = labels
    return labels


def capabilities() -> dict[str, Any]:
    model = _model_path()
    labels = _labels_path()
    try:
        import numpy  # type: ignore[import-not-found]  # noqa: F401
        import onnxruntime  # type: ignore[import-not-found]  # noqa: F401
        runtime = True
    except ImportError:
        runtime = False
    model_ready = bool(model and model.exists())
    labels_ready = bool(labels and labels.exists())
    return {
        "runtime_installed": runtime,
        "model": str(model) if model else None,
        "model_ready": model_ready,
        "labels": str(labels) if labels else None,
        "labels_ready": labels_ready,
        "input_size": int(settings.image_classifier_input_size),
        "ready": bool(runtime and model_ready and labels_ready),
        "engine": "ONNX whole-image subject/object tagger",
        "mode": "whole_image_classification",
        "cloud": False,
    }


def _session():
    caps = capabilities()
    if not caps["ready"]:
        raise SubjectEngineUnavailable(
            "Configure DS_IMAGE_CLASSIFIER_MODEL and DS_IMAGE_CLASSIFIER_LABELS "
            "and install the vision dependency group"
        )
    import onnxruntime as ort  # type: ignore[import-not-found]

    model = str(_model_path().resolve())
    cached = _session_cache.get(model)
    if cached is not None:
        return cached
    session = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    _session_cache[model] = session
    return session


def _softmax(values):
    import numpy as np  # type: ignore[import-not-found]

    vector = np.asarray(values, dtype=np.float32).reshape(-1)
    shifted = vector - float(vector.max(initial=0.0))
    exp = np.exp(shifted)
    total = float(exp.sum())
    return exp / total if total else exp


def classify_image(
    path: str | Path,
    *,
    top_k: int = 8,
    min_score: float = 0.03,
) -> list[dict[str, Any]]:
    import numpy as np  # type: ignore[import-not-found]

    session = _session()
    labels = _load_labels(_labels_path())
    size = max(32, int(settings.image_classifier_input_size))
    image_path = Path(path).expanduser().resolve(strict=True)

    with Image.open(image_path) as image:
        image = image.convert("RGB")
        # Standard ImageNet-style preprocessing. The configured model is expected
        # to accept NCHW float32 RGB tensors.
        width, height = image.size
        scale = size / min(width, height)
        resized = image.resize(
            (max(size, round(width * scale)), max(size, round(height * scale))),
            Image.Resampling.BILINEAR,
        )
        left = max(0, (resized.width - size) // 2)
        top = max(0, (resized.height - size) // 2)
        cropped = resized.crop((left, top, left + size, top + size))
        array = np.asarray(cropped, dtype=np.float32) / 255.0

    mean = np.asarray([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.asarray([0.229, 0.224, 0.225], dtype=np.float32)
    array = (array - mean) / std
    tensor = np.transpose(array, (2, 0, 1))[None, ...]

    input_meta = session.get_inputs()[0]
    outputs = session.run(None, {input_meta.name: tensor})
    if not outputs:
        raise ValueError("Classifier returned no outputs")
    scores = _softmax(outputs[0])
    count = min(len(labels), int(scores.shape[0]))
    order = np.argsort(scores[:count])[::-1]
    result: list[dict[str, Any]] = []
    for index in order[: max(1, min(50, int(top_k)))]:
        score = float(scores[int(index)])
        if score < float(min_score):
            continue
        result.append(
            {
                "label": labels[int(index)],
                "score": score,
                "class_index": int(index),
            }
        )
    return result


def _model_key() -> str:
    model = _model_path()
    labels = _labels_path()
    return "|".join(
        [
            str(model.resolve()) if model and model.exists() else "",
            str(labels.resolve()) if labels and labels.exists() else "",
            str(settings.image_classifier_input_size),
        ]
    )


def analyze_subjects(
    scan_id: int,
    *,
    limit: int | None = None,
    top_k: int = 8,
    min_score: float = 0.03,
) -> dict[str, Any]:
    init_database()
    if not capabilities()["ready"]:
        raise SubjectEngineUnavailable("Local image classifier is not ready")

    with connect() as connection:
        rows = connection.execute(
            "SELECT id,path FROM files WHERE scan_id=? AND category='photo' ORDER BY id",
            (int(scan_id),),
        ).fetchall()
    if limit is not None:
        rows = rows[: max(1, int(limit))]

    model_key = _model_key()
    analyzed = 0
    errors = 0
    tags_written = 0
    for row in rows:
        try:
            tags = classify_image(
                row["path"],
                top_k=top_k,
                min_score=min_score,
            )
        except (OSError, ValueError):
            errors += 1
            continue

        with connect() as connection:
            connection.execute(
                "DELETE FROM image_subject_tags WHERE scan_id=? AND file_id=? AND model_key=?",
                (int(scan_id), int(row["id"]), model_key),
            )
            connection.executemany(
                """
                INSERT INTO image_subject_tags(
                    scan_id,file_id,path,label,score,model_key,analyzed_at
                ) VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP)
                """,
                [
                    (
                        int(scan_id),
                        int(row["id"]),
                        str(row["path"]),
                        str(tag["label"]),
                        float(tag["score"]),
                        model_key,
                    )
                    for tag in tags
                ],
            )
            connection.commit()
        analyzed += 1
        tags_written += len(tags)

    return {
        "scan_id": int(scan_id),
        "photos_analyzed": analyzed,
        "tags_written": tags_written,
        "errors": errors,
        "model_key": model_key,
        "mode": "whole_image_classification",
    }


def search_subjects(
    scan_id: int,
    query: str,
    *,
    min_score: float = 0.05,
    limit: int = 200,
) -> list[dict[str, Any]]:
    init_database()
    clean = str(query or "").strip()
    if not clean:
        return []
    bounded = max(1, min(1000, int(limit)))
    like = f"%{clean}%"
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT
                file_id,
                path,
                MAX(score) AS score,
                GROUP_CONCAT(label, ', ') AS matched_labels
            FROM image_subject_tags
            WHERE scan_id=?
              AND label LIKE ? COLLATE NOCASE
              AND score>=?
            GROUP BY file_id,path
            ORDER BY score DESC,path
            LIMIT ?
            """,
            (int(scan_id), like, float(min_score), bounded),
        ).fetchall()
    return [dict(row) for row in rows]


def top_subjects(scan_id: int, limit: int = 50) -> list[dict[str, Any]]:
    init_database()
    bounded = max(1, min(500, int(limit)))
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT label,COUNT(DISTINCT file_id) AS photos,AVG(score) AS average_score,
                   MAX(score) AS max_score
            FROM image_subject_tags
            WHERE scan_id=?
            GROUP BY label
            ORDER BY photos DESC,max_score DESC
            LIMIT ?
            """,
            (int(scan_id), bounded),
        ).fetchall()
    return [dict(row) for row in rows]
