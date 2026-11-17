from __future__ import annotations

from labs.streaming_cdc import cli


def test_startup_log_redaction_removes_local_passwords(tmp_path, monkeypatch):
    local_env = tmp_path / "w8.env"
    local_env.write_text(
        "POSTGRES_PASSWORD=local-password-value\n"
        "DATAFORGE_W8_DB_PASSWORD=local-password-value\n"
        "DATAFORGE_W8_TOKEN=local-token-value\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "LOCAL_ENV_FILE", local_env)

    redacted = cli._redact_local_secrets(
        "password=local-password-value token=local-token-value"
    )

    assert "local-password-value" not in redacted
    assert "local-token-value" not in redacted
    assert redacted == "password=[REDACTED] token=[REDACTED]"
