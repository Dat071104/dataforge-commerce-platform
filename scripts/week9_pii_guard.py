"""Fail a PR manifest when raw personal-data columns leave restricted_pii."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dataforge.settings import ROOT

DEFAULT_MANIFEST = ROOT / "dbt" / "dataforge" / "target" / "manifest.json"
DIRECT_PII_TYPES = {
    "full_name",
    "national_id",
    "email",
    "phone_number",
    "date_of_birth",
}
INDIRECT_PII_TYPES = {"indirect_customer_identifier"}
NON_PUBLIC_PII_TYPES = DIRECT_PII_TYPES | INDIRECT_PII_TYPES | {
    "pseudonymous_customer_identifier",
    "masked_email",
}
RESTRICTED_SCHEMA = "restricted_pii"


class ManifestGuardError(RuntimeError):
    """Raised when the dbt manifest is missing or structurally incomplete."""


@dataclass(frozen=True)
class Finding:
    check_id: str
    model: str
    column: str
    classification: str
    pii_type: str
    restricted_source_ancestor: bool
    reason: str


@dataclass(frozen=True)
class GuardResult:
    models_scanned: int
    restricted_sources_scanned: int
    findings: list[Finding]


def _normalized(value: Any) -> str:
    return value.strip().lower() if isinstance(value, str) else ""


def _columns(owner_id: str, owner: dict[str, Any]) -> dict[str, dict[str, Any]]:
    columns = owner.get("columns")
    if not isinstance(columns, dict):
        raise ManifestGuardError(f"Manifest columns are missing for {owner_id}")
    return columns


def _metadata(owner_id: str, column_name: str, column: dict[str, Any]) -> tuple[str, str]:
    meta = column.get("meta")
    if not isinstance(meta, dict):
        raise ManifestGuardError(f"Manifest column metadata is missing for {owner_id}.{column_name}")
    classification = _normalized(meta.get("classification"))
    pii_type = _normalized(meta.get("pii_type"))
    if not classification or not pii_type:
        raise ManifestGuardError(f"Manifest classification or pii_type is missing for {owner_id}.{column_name}")
    return classification, pii_type


def _is_restricted_source(source: dict[str, Any]) -> bool:
    return (
        _normalized(source.get("source_name")) == RESTRICTED_SCHEMA
        or _normalized(source.get("schema")) == RESTRICTED_SCHEMA
    )


def _parents_for(unique_id: str, node: dict[str, Any], manifest: dict[str, Any]) -> list[str]:
    depends_on = node.get("depends_on", {})
    parents = depends_on.get("nodes", []) if isinstance(depends_on, dict) else []
    if isinstance(parents, list) and parents:
        return parents
    parent_map = manifest.get("parent_map", {})
    if isinstance(parent_map, dict) and isinstance(parent_map.get(unique_id), list):
        return parent_map[unique_id]
    return []


def _has_restricted_source_ancestor(
    unique_id: str,
    node: dict[str, Any],
    manifest: dict[str, Any],
    source_ids: set[str],
) -> bool:
    nodes = manifest.get("nodes", {})
    sources = manifest.get("sources", {})
    if not isinstance(nodes, dict) or not isinstance(sources, dict):
        raise ManifestGuardError("Manifest nodes or sources mapping is malformed")
    all_resources = {**nodes, **sources}
    pending = list(_parents_for(unique_id, node, manifest))
    visited: set[str] = set()
    while pending:
        parent_id = pending.pop()
        if parent_id in visited:
            continue
        visited.add(parent_id)
        if parent_id in source_ids:
            return True
        parent = all_resources.get(parent_id)
        if isinstance(parent, dict):
            pending.extend(_parents_for(parent_id, parent, manifest))
    return False


def scan_manifest(manifest: dict[str, Any]) -> GuardResult:
    """Check output-column metadata and restricted-source lineage in a dbt manifest."""
    nodes = manifest.get("nodes")
    sources = manifest.get("sources", {})
    if not isinstance(nodes, dict) or not isinstance(sources, dict):
        raise ManifestGuardError("Manifest must contain nodes and sources mappings")

    restricted_source_ids: set[str] = set()
    for unique_id, source in sources.items():
        if not isinstance(source, dict) or not _is_restricted_source(source):
            continue
        restricted_source_ids.add(unique_id)
        for column_name, column in _columns(unique_id, source).items():
            classification, pii_type = _metadata(unique_id, column_name, column)
            if classification == "restricted" and pii_type not in DIRECT_PII_TYPES:
                raise ManifestGuardError(
                    f"Restricted source metadata has an unsupported pii_type for {unique_id}.{column_name}"
                )

    findings: list[Finding] = []
    models_scanned = 0
    for unique_id, node in nodes.items():
        if not isinstance(node, dict) or node.get("resource_type") != "model":
            continue
        models_scanned += 1
        model_name = str(node.get("name") or unique_id)
        schema = _normalized(node.get("schema"))
        restricted_output = schema == RESTRICTED_SCHEMA
        restricted_ancestry = _has_restricted_source_ancestor(
            unique_id, node, manifest, restricted_source_ids
        )

        for column_name, column in _columns(unique_id, node).items():
            if not isinstance(column, dict):
                raise ManifestGuardError(f"Manifest column is malformed for {unique_id}.{column_name}")
            meta = column.get("meta")
            if not isinstance(meta, dict):
                raise ManifestGuardError(f"Manifest column metadata is missing for {unique_id}.{column_name}")
            classification = _normalized(meta.get("classification"))
            pii_type = _normalized(meta.get("pii_type"))
            if not classification or not pii_type:
                raise ManifestGuardError(
                    f"Manifest classification or pii_type is missing for {unique_id}.{column_name}"
                )

            reason = ""
            if not restricted_output and (
                classification == "restricted"
                or pii_type in DIRECT_PII_TYPES
            ):
                reason = "direct personal data is projected outside restricted_pii"
            elif classification == "public" and pii_type in NON_PUBLIC_PII_TYPES:
                reason = "personal or pseudonymous data is classified as public"

            if reason:
                findings.append(
                    Finding(
                        check_id="F13",
                        model=model_name,
                        column=column_name,
                        classification=classification or "unclassified",
                        pii_type=pii_type or "unclassified",
                        restricted_source_ancestor=restricted_ancestry,
                        reason=reason,
                    )
                )
    return GuardResult(
        models_scanned=models_scanned,
        restricted_sources_scanned=len(restricted_source_ids),
        findings=findings,
    )


def scan_manifest_file(path: Path) -> GuardResult:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestGuardError(f"Could not load dbt manifest: {path}") from exc
    if not isinstance(manifest, dict):
        raise ManifestGuardError("dbt manifest root must be a JSON object")
    return scan_manifest(manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    try:
        result = scan_manifest_file(args.manifest)
    except ManifestGuardError as exc:
        print(f"PII_GUARD_STATUS=UNVERIFIED reason={exc}", file=sys.stderr)
        return 2
    if result.findings:
        for finding in result.findings:
            print("PII_GUARD_FINDING=" + json.dumps(asdict(finding), sort_keys=True))
        print(
            "PII_GUARD_STATUS=FAIL "
            + json.dumps(
                {
                    "models_scanned": result.models_scanned,
                    "restricted_sources_scanned": result.restricted_sources_scanned,
                    "findings": len(result.findings),
                },
                sort_keys=True,
            )
        )
        return 1
    print(
        "PII_GUARD_STATUS=PASS "
        + json.dumps(
            {
                "models_scanned": result.models_scanned,
                "restricted_sources_scanned": result.restricted_sources_scanned,
                "findings": 0,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
