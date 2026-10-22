from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import backend.vault.service as vault


def test_vault_status_exposes_write_gate():
    status = vault.vault_status()
    assert status["writes_allowed"] is False
    assert status["kdf"] == "Argon2id"


def test_vault_can_import_directory_tree_and_restore_relative_path(tmp_path, monkeypatch):
    vault_root = tmp_path / "vault"
    monkeypatch.setattr(
        vault,
        "settings",
        SimpleNamespace(vault_root=vault_root, allow_vault_writes=True),
    )

    source = tmp_path / "source"
    nested = source / "docs" / "private"
    nested.mkdir(parents=True)
    (source / "top.txt").write_text("top", encoding="utf-8")
    (nested / "secret.txt").write_text("secret", encoding="utf-8")

    vault.create_vault("123", "correct horse battery staple")
    session = vault.unlock("123", "correct horse battery staple")
    token = session["token"]

    result = vault.import_path(token, source)

    assert result["kind"] == "directory"
    assert result["files"] == 2
    relative_paths = {item["relative_path"] for item in result["items"]}
    assert relative_paths == {"top.txt", str(vault.Path("docs") / "private" / "secret.txt")}

    items = vault.list_items(token)
    secret = next(item for item in items if item["name"] == "secret.txt")
    destination = tmp_path / "restore"
    destination.mkdir()

    restored = vault.export_file(token, secret["id"], destination)

    assert vault.Path(restored["path"]).read_text(encoding="utf-8") == "secret"
    assert vault.Path(restored["path"]).relative_to(destination) == vault.Path(
        "docs"
    ) / "private" / "secret.txt"



def test_vault_create_can_choose_and_persist_location(tmp_path, monkeypatch):
    default_root = tmp_path / "data" / "vault"
    data_dir = tmp_path / "data"
    selected_root = tmp_path / "storage" / "DiskShellVault"
    monkeypatch.setattr(
        vault,
        "settings",
        SimpleNamespace(
            vault_root=default_root,
            vault_root_raw="",
            data_dir=data_dir,
            allow_vault_writes=True,
        ),
    )

    created = vault.create_vault(
        "operator",
        "correct horse battery staple",
        root=selected_root,
    )

    assert created["root"] == str(selected_root.resolve())
    assert (selected_root / "vault.json").exists()
    assert (selected_root / "catalog.bin").exists()
    assert (selected_root / "objects").is_dir()
    assert not (default_root / "vault.json").exists()

    locator = json.loads((data_dir / vault.VAULT_LOCATION_FILE).read_text(encoding="utf-8"))
    assert locator["root"] == str(selected_root.resolve())

    status = vault.vault_status()
    assert status["initialized"] is True
    assert status["root"] == str(selected_root.resolve())
    assert status["location_mode"] == "saved"
    assert status["location_editable"] is False


def test_vault_create_rejects_volume_root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        vault,
        "settings",
        SimpleNamespace(
            vault_root=tmp_path / "data" / "vault",
            vault_root_raw="",
            data_dir=tmp_path / "data",
            allow_vault_writes=True,
        ),
    )

    with pytest.raises(vault.VaultError, match="folder inside the volume"):
        vault.create_vault(
            "operator",
            "correct horse battery staple",
            root=tmp_path.anchor,
        )


def test_env_vault_root_cannot_be_overridden_from_ui(tmp_path, monkeypatch):
    forced_root = tmp_path / "forced-vault"
    monkeypatch.setattr(
        vault,
        "settings",
        SimpleNamespace(
            vault_root=forced_root,
            vault_root_raw=str(forced_root),
            data_dir=tmp_path / "data",
            allow_vault_writes=True,
        ),
    )

    with pytest.raises(vault.VaultError, match="fixed by DS_VAULT_ROOT"):
        vault.create_vault(
            "operator",
            "correct horse battery staple",
            root=tmp_path / "other-vault",
        )
