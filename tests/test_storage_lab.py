from backend.storage_lab.service import CLASS_LANES


def test_storage_lab_has_mixed_lanes():
    assert CLASS_LANES["video"] != CLASS_LANES["photo"]
    assert CLASS_LANES["document"] == CLASS_LANES["code"]
