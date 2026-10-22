from __future__ import annotations

from types import SimpleNamespace

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
