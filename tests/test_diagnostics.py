from backend.diagnostics.jobs import _classify_cells, _rating


def test_surface_classifier_marks_relative_slow_regions():
    cells = [
        {"mib_s": 120.0, "error": None, "status": "good"},
        {"mib_s": 110.0, "error": None, "status": "good"},
        {"mib_s": 100.0, "error": None, "status": "good"},
        {"mib_s": 8.0, "error": None, "status": "good"},
    ]

    warn, slow, median = _classify_cells(cells)

    assert median is not None
    assert warn == 0
    assert slow == 1
    assert cells[-1]["status"] == "slow"


def test_surface_rating_is_bad_on_raw_read_error():
    job = {
        "health_status": "Healthy",
        "reliability": {
            "temperature_c": 35,
            "power_on_hours": 100,
            "read_errors_total": 0,
            "write_errors_total": 0,
            "wear": None,
        },
        "read_errors": 1,
        "slow_cells": 0,
        "warn_cells": 0,
    }

    assert _rating(job) == "Bad"


def test_surface_rating_can_be_excellent_with_clean_reliability_data():
    job = {
        "health_status": "Healthy",
        "reliability": {
            "temperature_c": 35,
            "power_on_hours": 100,
            "read_errors_total": 0,
            "write_errors_total": 0,
            "wear": None,
        },
        "read_errors": 0,
        "slow_cells": 0,
        "warn_cells": 0,
    }

    assert _rating(job) == "Excellent"
