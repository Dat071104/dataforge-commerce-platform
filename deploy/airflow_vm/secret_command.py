#!/usr/bin/env python3
"""Read Airflow configuration secrets from Compose mounts backed by host tmpfs."""

from __future__ import annotations

import hashlib
import hmac
import sys
from pathlib import Path
from urllib.parse import quote

SECRET_ROOT = Path("/run/secrets")
SECRET_FILES = {
    "fernet-key": SECRET_ROOT / "fernet_key",
    "metadata-db-password": SECRET_ROOT / "metadata_db_password",
}
API_SECRET_CONTEXT = b"dataforge-airflow-api-secret-v1"
JWT_SECRET_CONTEXT = b"dataforge-airflow-jwt-secret-v1"


def _read_secret(name: str) -> str:
    path = SECRET_FILES.get(name)
    if path is None:
        raise RuntimeError("Unsupported Airflow secret name")
    try:
        value = path.read_text(encoding="utf-8")
    except OSError:
        raise RuntimeError("Required tmpfs secret is unavailable") from None
    if not value or any(ord(character) < 32 for character in value):
        raise RuntimeError("Required tmpfs secret is invalid")
    return value


def _derive_secret(fernet_key: str, context: bytes) -> str:
    return hmac.new(fernet_key.encode("ascii"), context, hashlib.sha256).hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    action = sys.argv[1]
    if action == "fernet-key":
        value = _read_secret("fernet-key")
    elif action == "database-url":
        password = quote(_read_secret("metadata-db-password"), safe="")
        value = (
            "postgresql+psycopg2://airflow:"
            f"{password}@postgres:5432/airflow"
        )
    elif action == "api-secret":
        value = _derive_secret(_read_secret("fernet-key"), API_SECRET_CONTEXT)
    elif action == "jwt-secret":
        value = _derive_secret(_read_secret("fernet-key"), JWT_SECRET_CONTEXT)
    else:
        return 2
    sys.stdout.write(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
