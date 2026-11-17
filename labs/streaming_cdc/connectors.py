"""Idempotent Debezium connector registration over the Connect REST API."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

CONNECTOR_CONFIG = Path(__file__).with_name("config") / "postgres_connector.json"
CONNECTOR_NAME = "dataforge-w8-postgres"


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
) -> requests.Response:
    return session.request(method, url, json=payload, timeout=10)


def register_or_update_connector(connect_url: str, *, wait_seconds: int = 180) -> dict[str, Any]:
    """Create or update the named connector and wait for its task to run."""
    definition = json.loads(CONNECTOR_CONFIG.read_text(encoding="utf-8"))
    name = definition["name"]
    config = definition["config"]
    password = os.environ.get("DATAFORGE_W8_DB_PASSWORD")
    if not password:
        raise RuntimeError("DATAFORGE_W8_DB_PASSWORD is missing; run the Week 8 CLI first")
    config["database.password"] = password
    base = connect_url.rstrip("/")

    with requests.Session() as session:
        existing = _request_json(session, "GET", f"{base}/connectors/{name}/config")
        if existing.status_code == 404:
            created = _request_json(
                session,
                "POST",
                f"{base}/connectors",
                payload={"name": name, "config": config},
            )
            if created.status_code not in {200, 201}:
                created.raise_for_status()
        else:
            existing.raise_for_status()
            updated = _request_json(
                session, "PUT", f"{base}/connectors/{name}/config", payload=config
            )
            updated.raise_for_status()

        deadline = time.monotonic() + wait_seconds
        last_status: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            response = _request_json(session, "GET", f"{base}/connectors/{name}/status")
            if response.status_code == 200:
                last_status = response.json()
                connector_state = last_status.get("connector", {}).get("state")
                task_states = [task.get("state") for task in last_status.get("tasks", [])]
                if connector_state == "RUNNING" and all(
                    state == "RUNNING" for state in task_states
                ):
                    return last_status
                if connector_state == "FAILED" or "FAILED" in task_states:
                    raise RuntimeError(f"Debezium connector failed: {last_status}")
            time.sleep(2)
        raise TimeoutError(f"Debezium connector did not become RUNNING: {last_status}")
