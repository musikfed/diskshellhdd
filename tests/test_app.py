import backend.core.database as database
from backend.app import VERSION, create_app


def test_health_endpoint():
    client = create_app().test_client()
    response = client.get("/api/health")

    assert response.status_code == 200

    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["version"] == VERSION
    assert payload["python_only"] is True



def test_workspace_state_api_is_backend_persistent(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace-api.db")
    client = create_app().test_client()

    response = client.patch(
        "/api/ui-state",
        json={
            "active_page": "streamcopy",
            "active_volume": "W:\\",
            "scan_id": "77",
        },
    )
    assert response.status_code == 200

    restored = client.get("/api/ui-state")
    assert restored.status_code == 200
    payload = restored.get_json()
    assert payload["active_page"] == "streamcopy"
    assert payload["active_volume"] == "W:\\"
    assert payload["scan_id"] == "77"
    assert payload["scope"] == "local_backend"



def test_workspace_api_isolates_view_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace-view-api.db")
    client = create_app().test_client()

    first = client.patch(
        "/api/ui-state",
        json={
            "view_id": "browser-a",
            "active_page": "files",
            "view_state": {"commanderJobId": "job-a"},
        },
    )
    second = client.patch(
        "/api/ui-state",
        json={
            "view_id": "browser-b",
            "active_page": "disks",
            "view_state": {"commanderJobId": "job-b"},
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200

    restored_a = client.get("/api/ui-state?view_id=browser-a").get_json()
    restored_b = client.get("/api/ui-state?view_id=browser-b").get_json()
    assert restored_a["active_page"] == "files"
    assert restored_a["view_state"]["commanderJobId"] == "job-a"
    assert restored_b["active_page"] == "disks"
    assert restored_b["view_state"]["commanderJobId"] == "job-b"
