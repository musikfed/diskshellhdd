from backend.vault.service import vault_status


def test_vault_status_exposes_write_gate():
    status = vault_status()
    assert status["writes_allowed"] is False
    assert status["kdf"] == "Argon2id"
