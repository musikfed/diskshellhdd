from __future__ import annotations

from types import SimpleNamespace

import backend.files.write_authorization as write_auth


def test_runtime_file_write_toggle(monkeypatch):
    monkeypatch.setattr(
        write_auth,
        "settings",
        SimpleNamespace(allow_file_writes=False),
    )

    write_auth.set_runtime_file_writes(False)
    assert write_auth.file_write_state()["allowed"] is False

    enabled = write_auth.set_runtime_file_writes(True)
    assert enabled["allowed"] is True
    assert enabled["runtime_enabled"] is True
    assert enabled["mode"] == "manual_until_restart"

    disabled = write_auth.set_runtime_file_writes(False)
    assert disabled["allowed"] is False


def test_environment_override_keeps_file_writes_enabled(monkeypatch):
    monkeypatch.setattr(
        write_auth,
        "settings",
        SimpleNamespace(allow_file_writes=True),
    )
    write_auth.set_runtime_file_writes(False)

    state = write_auth.file_write_state()

    assert state["allowed"] is True
    assert state["global_override"] is True
