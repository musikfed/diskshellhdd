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
