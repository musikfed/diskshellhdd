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



def test_workspace_view_state_merges_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace-view.db")

    first = update_workspace_state(
        active_page="search",
        view_state={
            "fileLeftPath": "H:\\",
            "commanderActiveSide": "right",
            "pageScroll:search": 240,
        },
    )
    assert first["active_page"] == "search"
    assert first["view_state"]["fileLeftPath"] == "H:\\"
    assert first["view_state"]["commanderActiveSide"] == "right"

    second = update_workspace_state(
        view_state={
            "fileRightPath": "W:\\",
            "pageScroll:search": 480,
            "commanderActiveSide": None,
        }
    )
    assert second["view_state"]["fileLeftPath"] == "H:\\"
    assert second["view_state"]["fileRightPath"] == "W:\\"
    assert second["view_state"]["pageScroll:search"] == 480
    assert "commanderActiveSide" not in second["view_state"]

    restored = get_workspace_state()
    assert restored["view_state"] == second["view_state"]


def test_workspace_accepts_relocation_page(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace-relocation.db")
    state = update_workspace_state(active_page="relocation")
    assert state["active_page"] == "relocation"



def test_workspace_read_remains_available_while_writer_transaction_is_open(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace-wal.db")
    initial = get_workspace_state()
    assert initial["active_page"] == "dashboard"

    blocker = database.connect()
    try:
        blocker.execute("BEGIN IMMEDIATE")
        blocker.execute(
            "UPDATE workspace_state SET active_page='files' WHERE id=1"
        )

        # WAL readers must still see the last committed workspace state.
        # This specifically protects GET /api/ui-state from becoming a write.
        visible = get_workspace_state()
        assert visible["active_page"] == "dashboard"
    finally:
        blocker.rollback()
        blocker.close()


def test_workspace_update_uses_single_connection_for_view_state(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace-single.db")
    get_workspace_state()

    real_connect = database.connect
    calls = 0

    def counted_connect():
        nonlocal calls
        calls += 1
        return real_connect()

    monkeypatch.setattr("backend.ui_state.service.connect", counted_connect)

    state = update_workspace_state(
        active_page="files",
        view_state={"fileLeftPath": "H:\\"},
    )

    assert state["active_page"] == "files"
    assert state["view_state"]["fileLeftPath"] == "H:\\"
    assert calls == 1



def test_parallel_browser_views_do_not_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace-views.db")

    first = update_workspace_state(
        view_id="tab-a",
        active_page="files",
        active_volume="H:\\",
        view_state={"fileLeftPath": "H:\\source"},
        promote_default=True,
    )
    second = update_workspace_state(
        view_id="tab-b",
        active_page="disks",
        active_volume="W:\\",
        view_state={"pageScroll:disks": 900},
        promote_default=True,
    )

    assert first["view_id"] == "tab-a"
    assert second["view_id"] == "tab-b"

    restored_a = get_workspace_state("tab-a")
    restored_b = get_workspace_state("tab-b")
    assert restored_a["active_page"] == "files"
    assert restored_a["active_volume"] == "H:\\"
    assert restored_a["view_state"]["fileLeftPath"] == "H:\\source"
    assert restored_b["active_page"] == "disks"
    assert restored_b["active_volume"] == "W:\\"
    assert restored_b["view_state"]["pageScroll:disks"] == 900

    # A brand-new view inherits the last promoted default, but existing views
    # keep their own navigation and context.
    new_view = get_workspace_state("tab-c")
    assert new_view["inherited_default"] is True
    assert new_view["active_page"] == "disks"
    assert get_workspace_state("tab-a")["active_page"] == "files"


def test_detached_view_never_promotes_global_default(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace-detached.db")

    update_workspace_state(
        view_id="main-tab",
        active_page="files",
        promote_default=True,
    )
    detached = update_workspace_state(
        view_id="monitor-2",
        active_page="streamcopy",
        detached=True,
        promote_default=False,
    )

    assert detached["active_page"] == "streamcopy"
    assert detached["detached"] is True
    assert get_workspace_state("monitor-2")["active_page"] == "streamcopy"
    assert get_workspace_state()["active_page"] == "files"
    assert get_workspace_state("brand-new")["active_page"] == "files"


def test_view_state_patch_is_isolated_between_tabs(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "workspace-view-patch.db")

    update_workspace_state(
        view_id="tab-one",
        view_state={"commanderJobId": "job-1", "fileLeftPath": "H:\\"},
    )
    update_workspace_state(
        view_id="tab-two",
        view_state={"commanderJobId": "job-2", "fileLeftPath": "W:\\"},
    )

    one = get_workspace_state("tab-one")
    two = get_workspace_state("tab-two")
    assert one["view_state"]["commanderJobId"] == "job-1"
    assert one["view_state"]["fileLeftPath"] == "H:\\"
    assert two["view_state"]["commanderJobId"] == "job-2"
    assert two["view_state"]["fileLeftPath"] == "W:\\"
