"""Run non-mutating W7 table-write permission probes for Week 9 CI."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request

WRITE_PERMISSION = "bigquery.tables.updateData"


def _post_json(url: str, token: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read())
        except json.JSONDecodeError:
            body = {}
        return error.code, body
    except (OSError, TimeoutError, json.JSONDecodeError):
        return 0, {}


def _error_message(payload: dict) -> str:
    error = payload.get("error", {})
    if not isinstance(error, dict):
        return ""
    message = error.get("message", "")
    return message.lower() if isinstance(message, str) else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    args = parser.parse_args()

    token = os.environ.get("W9_BQ_ACCESS_TOKEN", "")
    if not token:
        print("UNVERIFIED: access token was not provided to the permission probe")
        return 2

    base = (
        "https://bigquery.googleapis.com/bigquery/v2/projects/"
        f"{args.project}/datasets/weather_mini3/tables/weather_landing"
    )
    status, permission_result = _post_json(
        f"{base}:testIamPermissions",
        token,
        {"permissions": [WRITE_PERMISSION]},
    )
    if status != 200:
        print(f"UNVERIFIED: table permission probe returned HTTP {status}")
        return 2
    granted = permission_result.get("permissions", [])
    if WRITE_PERMISSION in granted:
        print("FAIL: BigQuery permission probe reports table update permission granted")
        return 1
    print(
        "ADVISORY: tables.testIamPermissions did not return table update permission; "
        "Google documents this endpoint may fail open."
    )

    query_result = _post_json(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{args.project}/queries",
        token,
        {
            "query": (
                f"UPDATE `{args.project}.weather_mini3.weather_landing` "
                "SET landed_at = landed_at WHERE FALSE"
            ),
            "useLegacySql": False,
            "dryRun": True,
            "location": "us-central1",
            "maximumBytesBilled": str(1024**3),
        },
    )
    query_status, query_error = query_result
    message = _error_message(query_error)
    if query_status == 403 and WRITE_PERMISSION.lower() in message:
        print(
            "PASS: BigQuery dry-run returned an authorization denial for "
            "bigquery.tables.updateData; no query executed and no production write occurred."
        )
        return 0
    if query_status == 200:
        print(
            "UNVERIFIED: BigQuery accepted the dry-run request; no query executed, "
            "but this is not evidence of write denial."
        )
        return 2
    print(
        f"UNVERIFIED: dry-run request returned HTTP {query_status} without the "
        "expected bigquery.tables.updateData authorization denial."
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
