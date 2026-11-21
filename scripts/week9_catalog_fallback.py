"""Write a sanitized OpenMetadata BigQuery result and Dataplex fallback reason."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

METADATA_PERMISSIONS = (
    "bigquery.datasets.get",
    "bigquery.tables.get",
    "bigquery.tables.getData",
    "bigquery.tables.list",
    "resourcemanager.projects.get",
    "bigquery.jobs.create",
    "bigquery.jobs.listAll",
    "datacatalog.taxonomies.get",
    "datacatalog.taxonomies.list",
)
_DENIAL_CONTEXT = re.compile(
    r"permission[_ ]denied|permission.{0,120}(?:denied|not granted|not have|missing)|"
    r"(?:denied|not authorized|access denied).{0,120}permission|\b403\b",
    re.IGNORECASE,
)


def denied_metadata_permissions(log_text: str) -> list[str]:
    """Return only recognized permission names that appear in a denial context."""
    denied: set[str] = set()
    for permission in METADATA_PERMISSIONS:
        permission_pattern = re.compile(
            rf"(?<![A-Za-z0-9_.]){re.escape(permission)}(?![A-Za-z0-9_.])",
            re.IGNORECASE,
        )
        for match in permission_pattern.finditer(log_text):
            start = max(0, match.start() - 220)
            end = min(len(log_text), match.end() + 220)
            if _DENIAL_CONTEXT.search(log_text[start:end]):
                denied.add(permission)
                break
    return [permission for permission in METADATA_PERMISSIONS if permission in denied]


def summarize_connector_result(
    *, auth_status: str, exit_code: int | None, log_text: str = ""
) -> dict[str, Any]:
    """Produce a receipt containing no raw connector output, identifiers, or values."""
    if auth_status == "failure":
        return {
            "status": "UNVERIFIED_AUTH_FAILURE",
            "denied_permissions": [],
            "dataplex_fallback_reason": (
                "WIF authentication failed; the BigQuery connector was not run. "
                "Use the approved G7 Dataplex lineage path after its integrator CI build and event."
            ),
        }

    if auth_status == "skipped":
        return {
            "status": "UNVERIFIED_AUTH_SKIPPED",
            "denied_permissions": [],
            "dataplex_fallback_reason": (
                "WIF authentication was skipped or an earlier catalog step did not complete; "
                "the BigQuery connector was not run. Use the approved G7 Dataplex lineage path "
                "after its integrator CI build and event."
            ),
        }

    if exit_code is None:
        return {
            "status": "UNVERIFIED_NOT_RUN",
            "denied_permissions": [],
            "dataplex_fallback_reason": (
                "No BigQuery connector exit status was recorded. Keep metadata evidence unverified; "
                "use the approved G7 Dataplex lineage path after its integrator CI build and event."
            ),
        }

    if exit_code == 0:
        return {
            "status": "PASS_METADATA_ONLY",
            "denied_permissions": [],
            "dataplex_fallback_reason": None,
        }

    denied = denied_metadata_permissions(log_text)
    if denied:
        reason = (
            "OpenMetadata BigQuery metadata ingestion was denied required permission(s): "
            + ", ".join(denied)
            + ". No IAM was changed; use the approved G7 Dataplex lineage path after its "
            "integrator CI build and event."
        )
        return {
            "status": "BLOCKED_PERMISSION",
            "denied_permissions": denied,
            "dataplex_fallback_reason": reason,
        }

    return {
        "status": "UNVERIFIED_FAILURE",
        "denied_permissions": [],
        "dataplex_fallback_reason": (
            "OpenMetadata BigQuery metadata ingestion failed without a recognized permission denial. "
            "Raw logs were suppressed; keep metadata evidence unverified and use the approved G7 "
            "Dataplex lineage path after its integrator CI build and event."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--auth-status", choices=("success", "failure", "skipped"), required=True)
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--log-file", type=Path)
    parser.add_argument("--summary-file", type=Path)
    args = parser.parse_args(argv)

    log_text = args.log_file.read_text(encoding="utf-8", errors="replace") if args.log_file and args.log_file.is_file() else ""
    result = summarize_connector_result(
        auth_status=args.auth_status,
        exit_code=args.exit_code,
        log_text=log_text,
    )
    record = "OPENMETADATA_BIGQUERY=" + json.dumps(result, sort_keys=True)
    print(record)
    if args.summary_file:
        with args.summary_file.open("a", encoding="utf-8") as summary:
            summary.write(record + "\n")
            if result["dataplex_fallback_reason"]:
                summary.write("DATAPLEX_FALLBACK_REASON=" + result["dataplex_fallback_reason"] + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
