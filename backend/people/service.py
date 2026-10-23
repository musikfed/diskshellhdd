from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from backend.config import settings
from backend.core.database import connect, init_database


class PeopleEngineUnavailable(RuntimeError):
    pass


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
        "ready": bool(runtime and detector and detector.exists() and recognizer and recognizer.exists()),
        "engine": "OpenCV YuNet + SFace",
        "cloud": False,
    }


def _detect_embeddings(path: Path) -> tuple[int, int, list[dict]]:
    caps = capabilities()
    if not caps["ready"]:
        raise PeopleEngineUnavailable("Configure local YuNet and SFace ONNX model paths")

    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    image = cv2.imread(str(path))
    if image is None:
        raise ValueError("Image could not be decoded")
    height, width = image.shape[:2]
    detector = cv2.FaceDetectorYN.create(
        settings.face_detector_model, "", (width, height), score_threshold=0.8
    )
    recognizer = cv2.FaceRecognizerSF.create(settings.face_recognizer_model, "")
    _status, faces = detector.detect(image)
    result: list[dict] = []
    if faces is None:
        return width, height, result

    for face in faces:
        aligned = recognizer.alignCrop(image, face)
        feature = recognizer.feature(aligned).astype("float32").reshape(-1)
        norm = float(np.linalg.norm(feature))
        if norm:
            feature = feature / norm
        result.append(
            {
                "x": float(face[0]),
                "y": float(face[1]),
                "width": float(face[2]),
                "height": float(face[3]),
                "score": float(face[-1]),
                "embedding": feature.tobytes(),
                "embedding_dim": int(feature.size),
            }
        )
    return width, height, result


def analyze_scan(scan_id: int, limit: int | None = None) -> dict:
    init_database()
    if not capabilities()["ready"]:
        raise PeopleEngineUnavailable("Local face models are not ready")

    with connect() as connection:
        query = "SELECT id, path FROM files WHERE scan_id=? AND category='photo' ORDER BY id"
        rows = connection.execute(query, (scan_id,)).fetchall()
        if limit is not None:
            rows = rows[:limit]

    analyzed = 0
    faces_total = 0
    errors = 0
    for row in rows:
        path = Path(row["path"])
        try:
            width, height, found = _detect_embeddings(path)
        except (OSError, ValueError):
            errors += 1
            continue
        with connect() as connection:
            existing = connection.execute(
                "SELECT id FROM photos WHERE scan_id=? AND file_id=?",
                (scan_id, row["id"]),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    "INSERT INTO photos(scan_id,file_id,path,width,height,faces_count) VALUES(?,?,?,?,?,?)",
                    (scan_id, row["id"], str(path), width, height, len(found)),
                )
                photo_id = int(cursor.lastrowid)
            else:
                photo_id = int(existing["id"])
                connection.execute("DELETE FROM faces WHERE photo_id=?", (photo_id,))
                connection.execute(
                    "UPDATE photos SET path=?,width=?,height=?,faces_count=?,analyzed_at=CURRENT_TIMESTAMP WHERE id=?",
                    (str(path), width, height, len(found), photo_id),
                )
            connection.executemany(
                """
                INSERT INTO faces(photo_id,x,y,width,height,score,embedding,embedding_dim)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                [
                    (
                        photo_id,
                        face["x"], face["y"], face["width"], face["height"],
                        face["score"], face["embedding"], face["embedding_dim"],
                    )
                    for face in found
                ],
            )
            connection.commit()
        analyzed += 1
        faces_total += len(found)

    people = cluster_scan(scan_id)
    return {
        "scan_id": scan_id,
        "photos_analyzed": analyzed,
        "faces": faces_total,
        "errors": errors,
        "persons": len(people),
    }


def cluster_scan(scan_id: int, threshold: float = 0.45) -> list[dict]:
    try:
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PeopleEngineUnavailable("Install the vision extra") from exc

    with connect() as connection:
        rows = connection.execute(
            """
            SELECT faces.id, faces.embedding, faces.embedding_dim
            FROM faces JOIN photos ON photos.id=faces.photo_id
            WHERE photos.scan_id=? AND faces.embedding IS NOT NULL ORDER BY faces.id
            """,
            (scan_id,),
        ).fetchall()

        # Rebuild auto clusters, preserving room for future manual persons.
        auto_ids = [
            row["id"]
            for row in connection.execute(
                "SELECT id FROM persons WHERE scan_id=? AND auto_cluster=1", (scan_id,)
            ).fetchall()
        ]
        if auto_ids:
            placeholders = ",".join("?" for _ in auto_ids)
            connection.execute(f"UPDATE faces SET person_id=NULL WHERE person_id IN ({placeholders})", auto_ids)
            connection.execute(f"DELETE FROM persons WHERE id IN ({placeholders})", auto_ids)

        clusters: list[dict] = []
        for row in rows:
            vector = np.frombuffer(row["embedding"], dtype=np.float32, count=row["embedding_dim"]).copy()
            best_index = None
            best_score = -1.0
            for idx, cluster in enumerate(clusters):
                score = float(np.dot(vector, cluster["centroid"]))
                if score > best_score:
                    best_score = score
                    best_index = idx
            if best_index is not None and best_score >= threshold:
                cluster = clusters[best_index]
                cluster["faces"].append(int(row["id"]))
                vectors = cluster["vectors"]
                vectors.append(vector)
                centroid = np.mean(vectors, axis=0)
                norm = float(np.linalg.norm(centroid))
                cluster["centroid"] = centroid / norm if norm else centroid
            else:
                clusters.append({"faces": [int(row["id"])], "vectors": [vector], "centroid": vector})

        result = []
        for index, cluster in enumerate(clusters, 1):
            cursor = connection.execute(
                "INSERT INTO persons(scan_id,name,auto_cluster) VALUES(?,?,1)",
                (scan_id, f"Person {index}"),
            )
            person_id = int(cursor.lastrowid)
            placeholders = ",".join("?" for _ in cluster["faces"])
            connection.execute(
                f"UPDATE faces SET person_id=? WHERE id IN ({placeholders})",
                [person_id, *cluster["faces"]],
            )
            result.append({"id": person_id, "name": f"Person {index}", "faces": len(cluster["faces"])})
        connection.commit()
    return result


def list_people(scan_id: int) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT persons.id, persons.name, COUNT(faces.id) AS faces,
                   COUNT(DISTINCT photos.id) AS photos,
                   MIN(faces.id) AS cover_face_id
            FROM persons
            LEFT JOIN faces ON faces.person_id=persons.id
            LEFT JOIN photos ON photos.id=faces.photo_id
            WHERE persons.scan_id=?
            GROUP BY persons.id, persons.name
            ORDER BY photos DESC, persons.id
            """,
            (scan_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def rename_person(person_id: int, name: str) -> dict:
    clean = name.strip()
    if not clean:
        raise ValueError("Person name cannot be empty")
    with connect() as connection:
        changed = connection.execute(
            "UPDATE persons SET name=?, auto_cluster=0 WHERE id=?", (clean, person_id)
        ).rowcount
        connection.commit()
    if not changed:
        raise KeyError(person_id)
    return {"id": person_id, "name": clean}


def person_photos(person_id: int, mode: str = "all") -> list[dict]:
    if mode not in {"all", "alone", "with_others"}:
        raise ValueError("mode must be all, alone or with_others")
    clause = ""
    if mode == "alone":
        clause = "AND photos.faces_count = 1"
    elif mode == "with_others":
        clause = "AND photos.faces_count > 1"
    with connect() as connection:
        rows = connection.execute(
            f"""
            SELECT DISTINCT photos.id, photos.path, photos.width, photos.height, photos.faces_count
            FROM photos JOIN faces ON faces.photo_id=photos.id
            WHERE faces.person_id=? {clause}
            ORDER BY photos.path
            """,
            (person_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def face_thumbnail(face_id: int, size: int = 256) -> bytes:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT faces.x,faces.y,faces.width,faces.height,photos.path
            FROM faces JOIN photos ON photos.id=faces.photo_id WHERE faces.id=?
            """,
            (face_id,),
        ).fetchone()
    if row is None:
        raise KeyError(face_id)
    with Image.open(row["path"]) as image:
        image = image.convert("RGB")
        margin = 0.25
        x0 = max(0, int(row["x"] - row["width"] * margin))
        y0 = max(0, int(row["y"] - row["height"] * margin))
        x1 = min(image.width, int(row["x"] + row["width"] * (1 + margin)))
        y1 = min(image.height, int(row["y"] + row["height"] * (1 + margin)))
        crop = image.crop((x0, y0, x1, y1))
        crop.thumbnail((size, size))
        output = io.BytesIO()
        crop.save(output, format="JPEG", quality=88)
        return output.getvalue()



def similar_faces(
    face_id: int,
    *,
    limit: int = 50,
    min_score: float = 0.35,
) -> list[dict]:
    try:
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PeopleEngineUnavailable("Install the vision extra") from exc

    bounded_limit = max(1, min(500, int(limit)))
    threshold = max(-1.0, min(1.0, float(min_score)))
    with connect() as connection:
        source = connection.execute(
            """
            SELECT faces.id,faces.embedding,faces.embedding_dim,photos.scan_id
            FROM faces
            JOIN photos ON photos.id=faces.photo_id
            WHERE faces.id=? AND faces.embedding IS NOT NULL
            """,
            (int(face_id),),
        ).fetchone()
        if source is None:
            raise KeyError(face_id)
        rows = connection.execute(
            """
            SELECT faces.id,faces.person_id,faces.embedding,faces.embedding_dim,
                   photos.id AS photo_id,photos.path,persons.name AS person_name
            FROM faces
            JOIN photos ON photos.id=faces.photo_id
            LEFT JOIN persons ON persons.id=faces.person_id
            WHERE photos.scan_id=?
              AND faces.id<>?
              AND faces.embedding IS NOT NULL
              AND faces.embedding_dim=?
            """,
            (
                int(source["scan_id"]),
                int(face_id),
                int(source["embedding_dim"]),
            ),
        ).fetchall()

    reference = np.frombuffer(
        source["embedding"],
        dtype=np.float32,
        count=int(source["embedding_dim"]),
    )
    matches = []
    for row in rows:
        candidate = np.frombuffer(
            row["embedding"],
            dtype=np.float32,
            count=int(row["embedding_dim"]),
        )
        score = float(np.dot(reference, candidate))
        if score < threshold:
            continue
        matches.append(
            {
                "face_id": int(row["id"]),
                "person_id": row["person_id"],
                "person_name": row["person_name"],
                "photo_id": int(row["photo_id"]),
                "path": str(row["path"]),
                "score": round(score, 6),
            }
        )
    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:bounded_limit]
