import pytest

from backend.storage_brain.executor import PlanExecutionBlocked, apply_plan
from backend.storage_brain.service import _is_within, _layout_hint, choose_storage_class


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


def test_plan_executor_is_locked_by_default():
    with pytest.raises(PlanExecutionBlocked):
        apply_plan(999999, "APPLY PLAN 999999")


def test_managed_import_scope_checks_path_membership(tmp_path):
    root = tmp_path / "source"
    nested = root / "nested" / "file.bin"
    outside = tmp_path / "other" / "file.bin"

    assert _is_within(nested, root)
    assert not _is_within(outside, root)


def test_layout_hint_maps_video_to_media_band():
    lane, target = _layout_hint("video")

    assert lane == "A-media-sequential"
    assert target > 0
