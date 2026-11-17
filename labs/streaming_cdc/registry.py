"""Small Confluent Schema Registry REST helpers."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import requests


def set_global_compatibility(registry_url: str, level: str = "BACKWARD") -> None:
    response = requests.put(
        f"{registry_url.rstrip('/')}/config",
        json={"compatibility": level},
        headers={"Content-Type": "application/vnd.schemaregistry.v1+json"},
        timeout=10,
    )
    response.raise_for_status()


def subject_schemas(registry_url: str, subject: str) -> dict[int, dict[str, Any]]:
    """Return registered writer schemas keyed by Confluent schema ID."""
    escaped = quote(subject, safe="")
    versions_response = requests.get(
        f"{registry_url.rstrip('/')}/subjects/{escaped}/versions", timeout=10
    )
    versions_response.raise_for_status()
    schemas: dict[int, dict[str, Any]] = {}
    for version in versions_response.json():
        response = requests.get(
            f"{registry_url.rstrip('/')}/subjects/{escaped}/versions/{int(version)}",
            timeout=10,
        )
        response.raise_for_status()
        item = response.json()
        schemas[int(item["id"])] = json.loads(item["schema"])
    return schemas


def latest_subject_schema(registry_url: str, subject: str) -> dict[str, Any]:
    escaped = quote(subject, safe="")
    response = requests.get(
        f"{registry_url.rstrip('/')}/subjects/{escaped}/versions/latest", timeout=10
    )
    response.raise_for_status()
    return json.loads(response.json()["schema"])
