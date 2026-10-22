from backend.people.service import capabilities


def test_people_engine_is_local_only():
    caps = capabilities()
    assert caps["cloud"] is False
    assert "YuNet" in caps["engine"]
