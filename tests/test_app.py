from backend.app import create_app


def test_health_endpoint():
    client = create_app().test_client()
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "ok"
    assert payload["version"] == "0.4.0"
    assert payload["python_only"] is True
    assert payload["safety"]["disk_writes"] is False
    assert payload["safety"]["file_writes"] is False
