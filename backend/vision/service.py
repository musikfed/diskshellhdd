from __future__ import annotations

from pathlib import Path

from backend.config import settings


def capabilities() -> dict:
    detector = Path(settings.face_detector_model) if settings.face_detector_model else None
    recognizer = Path(settings.face_recognizer_model) if settings.face_recognizer_model else None
    try:
        import cv2  # type: ignore[import-not-found]  # noqa: F401
        import numpy  # type: ignore[import-not-found]  # noqa: F401
        runtime = True
    except ImportError:
        runtime = False
    return {
        "runtime_installed": runtime,
        "detector_model": str(detector) if detector else None,
        "detector_ready": bool(detector and detector.exists()),
        "recognizer_model": str(recognizer) if recognizer else None,
        "recognizer_ready": bool(recognizer and recognizer.exists()),
        "engine": "OpenCV YuNet + SFace (optional local models)",
        "cloud": False,
    }


def detect_faces(path: str | Path) -> dict:
    caps = capabilities()
    if not (caps["runtime_installed"] and caps["detector_ready"]):
        return {"ready": False, "capabilities": caps, "faces": []}

    import cv2  # type: ignore[import-not-found]

    image_path = Path(path).expanduser().resolve(strict=True)
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError("Image could not be decoded")
    height, width = image.shape[:2]
    detector = cv2.FaceDetectorYN.create(
        settings.face_detector_model, "", (width, height), score_threshold=0.8
    )
    _result, faces = detector.detect(image)
    output = []
    if faces is not None:
        for row in faces:
            output.append(
                {
                    "x": float(row[0]),
                    "y": float(row[1]),
                    "width": float(row[2]),
                    "height": float(row[3]),
                    "score": float(row[-1]),
                }
            )
    return {"ready": True, "path": str(image_path), "faces": output}
