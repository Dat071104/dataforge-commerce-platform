"""HMAC-SHA256 pseudonymization for synthetic Week-9 customer profiles."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re

import requests

EXPECTED_PROJECT = "dataforge-p7-lab-d0f725"
EXPECTED_SECRET_NAME = "w9-pii-hmac-key"


class PseudonymizationError(RuntimeError):
    """Raised when the key, identity, or approved project is invalid."""


def hmac_customer_cccd(cccd: str, key: bytes) -> str:
    """Pseudonymize a reserved synthetic CCCD value without exposing the key."""
    if not key or len(key) < 32:
        raise PseudonymizationError("The HMAC key must contain at least 32 bytes")
    if not re.fullmatch(r"999\d{9}", cccd):
        raise PseudonymizationError("Synthetic CCCD must use prefix 999 and contain 12 digits")
    message = b"dataforge-week9-customer-cccd\0" + cccd.encode("ascii")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def load_hmac_key_from_secret_manager(project_id: str) -> bytes:
    """Read `w9-pii-hmac-key` from Secret Manager; never log the returned bytes."""
    if project_id != EXPECTED_PROJECT:
        raise PseudonymizationError("Secret lookup is restricted to the approved DataForge lab")
    try:
        import google.auth
        from google.auth.transport.requests import Request
    except ImportError as exc:  # pragma: no cover - requires the optional gcp extra
        raise PseudonymizationError("Secret lookup requires google-auth from the [gcp] extra") from exc

    credentials, adc_project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    if adc_project and adc_project != project_id:
        raise PseudonymizationError("ADC project differs from the approved DataForge target")
    credentials.refresh(Request())
    resource = f"projects/{project_id}/secrets/{EXPECTED_SECRET_NAME}/versions/latest:access"
    response = requests.get(
        f"https://secretmanager.googleapis.com/v1/{resource}",
        headers={"Authorization": f"Bearer {credentials.token}"},
        timeout=30,
    )
    if response.status_code >= 400:
        raise PseudonymizationError(f"Secret Manager access failed with HTTP {response.status_code}")
    try:
        key = base64.b64decode(response.json()["payload"]["data"], validate=True)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise PseudonymizationError("Secret Manager returned an invalid key payload") from exc
    if len(key) < 32:
        raise PseudonymizationError("Secret Manager HMAC key must contain at least 32 bytes")
    return key
