from __future__ import annotations

import backend.core.database as database
from backend.ui_state.service import get_workspace_state, update_workspace_state


def test_workspace_state_persists_without_browser_storage(tmp_path, monkeypatch):
    database_path = tmp_path / "workspace.db"
    monkeypatch.setattr(database, "DATABASE_PATH", database_path)

    initial = get_workspace_state()
    assert initial["active_page"] == "dashboard"
    assert initial["active_volume"] == ""
    assert initial["scan_id"] == ""
    assert initial["browser_independent"] is True

    saved = update_workspace_state(
        active_page="streamcopy",
        active_volume="W:\\",
        scan_id="42",
    )
    assert saved["active_page"] == "streamcopy"
    assert saved["active_volume"] == "W:\\"
    assert saved["scan_id"] == "42"

    restored = get_workspace_state()
    assert restored["active_page"] == "streamcopy"
    assert restored["active_volume"] == "W:\\"
    assert restored["scan_id"] == "42"


def test_workspace_state_allows_partial_updates_and_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace.db")

    update_workspace_state(
        active_page="files",
        active_volume="H:\\",
        scan_id="9",
    )
    value = update_workspace_state(active_page="diagnostics")

    assert value["active_page"] == "diagnostics"
    assert value["active_volume"] == "H:\\"
    assert value["scan_id"] == "9"

    cleared = update_workspace_state(active_volume="", scan_id="")
    assert cleared["active_volume"] == ""
    assert cleared["scan_id"] == ""


def test_workspace_state_rejects_unknown_page(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace.db")

    try:
        update_workspace_state(active_page="not-a-page")
    except ValueError as exc:
        assert "unknown page" in str(exc)
    else:
        raise AssertionError("expected unknown workspace page to be rejected")
