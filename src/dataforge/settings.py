"""Repository-relative paths. No secrets stored in source control."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SOURCE = DATA / "source"
BRONZE = DATA / "bronze"
MANIFESTS = DATA / "manifests"
QUARANTINE = DATA / "quarantine"
SQL = ROOT / "sql"


def database_url() -> str:
    """Read .env without requiring a dotenv dependency."""
    from urllib.parse import quote

    cfg: dict[str, str] = {}
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                cfg[key.strip()] = value.strip().strip('"').strip("'")
    for key in ("DATABASE_URL", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB",
                "POSTGRES_HOST", "POSTGRES_PORT"):
        if os.environ.get(key):
            cfg[key] = os.environ[key]
    if cfg.get("DATABASE_URL"):
        return cfg["DATABASE_URL"]
    user = quote(cfg.get("POSTGRES_USER", "dataforge"), safe="")
    pwd = quote(cfg.get("POSTGRES_PASSWORD", "replace_me_local_only"), safe="")
    host = cfg.get("POSTGRES_HOST", "127.0.0.1")
    port = cfg.get("POSTGRES_PORT", "5433")
    db = quote(cfg.get("POSTGRES_DB", "dataforge"), safe="")
    return f"postgresql://{user}:{pwd}@{host}:{port}/{db}"
