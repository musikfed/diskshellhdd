from collections import deque

from backend.storage_lab.service import (
    CLASS_LANES,
    GIB,
    LANE_POLICIES,
    MIB,
    _choose_lane,
    _effective_policy,
    _segment_lengths,
)


def test_storage_lab_has_mixed_lanes():
    assert CLASS_LANES["video"] != CLASS_LANES["photo"]
    assert CLASS_LANES["document"] == CLASS_LANES["code"]


def test_large_file_uses_bounded_equalized_extents():
    policy = _effective_policy(
        "A-media-sequential",
        sequential_mib_s=150,
        seek_ms=10,
        target_seek_overhead=0.02,
    )
    lengths = _segment_lengths(5 * GIB, policy)

    assert len(lengths) > 1
    assert max(lengths) <= LANE_POLICIES["A-media-sequential"]["max_band"]
    assert max(lengths) - min(lengths) <= 1


def test_small_file_is_not_fragmented():
    policy = _effective_policy(
        "C-interactive",
        sequential_mib_s=150,
        seek_ms=10,
        target_seek_overhead=0.02,
    )

    lengths = _segment_lengths(3 * MIB, policy)

    assert lengths == [3 * MIB]


def test_seek_cost_can_raise_minimum_band():
    policy = _effective_policy(
        "C-interactive",
        sequential_mib_s=200,
        seek_ms=12,
        target_seek_overhead=0.02,
    )

    assert policy["effective_min_band"] >= LANE_POLICIES["C-interactive"]["min_band"]
    assert policy["effective_target_band"] >= policy["effective_min_band"]
    assert policy["effective_target_band"] <= policy["max_band"]


def test_weighted_scheduler_avoids_same_lane_when_alternative_exists():
    policies = {
        "A-media-sequential": LANE_POLICIES["A-media-sequential"],
        "B-photo-mixed": LANE_POLICIES["B-photo-mixed"],
    }
    queues = {
        "A-media-sequential": deque([1, 2, 3]),
        "B-photo-mixed": deque([1, 2, 3]),
    }
    deficits: dict[str, int] = {}

    first = _choose_lane(queues, deficits, policies, None)
    second = _choose_lane(queues, deficits, policies, first)

    assert first != second
