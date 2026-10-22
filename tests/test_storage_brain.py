from backend.storage_brain.service import choose_storage_class


def test_placement_rule_selects_photo():
    rules = [
        {
            "name": "Photos",
            "category": "photo",
            "extension": None,
            "min_size": None,
            "max_size": None,
            "min_age_days": None,
            "target_class": "photos",
        }
    ]
    target, reason = choose_storage_class(
        {"category": "photo", "extension": ".jpg", "size": 10, "modified_ns": None},
        rules,
    )
    assert target == "photos"
    assert reason == "Photos"
