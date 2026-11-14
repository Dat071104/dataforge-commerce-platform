"""Create a sanitized, generation-pinned manifest for later C7 staging.

This offline helper never uploads or downloads data. The caller supplies
GCS object generations from a separately authorized read-only inventory after
the raw files have been uploaded with create-only preconditions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

MONTH_FILE = "yellow_tripdata_2024-01.parquet"
ZONE_FILE = "taxi_zone_lookup.csv"
MONTH_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet"
ZONE_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"


class StagingManifestError(ValueError):
    """The local source receipt or supplied GCS generation is invalid."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_manifest(
    source_manifest: dict[str, Any], *, trip_generation: str, zone_generation: str
) -> dict[str, Any]:
    if source_manifest.get("status") != "COMPLETE" or source_manifest.get("row_counts") != "NOT_RUN":
        raise StagingManifestError("local acquisition manifest must be COMPLETE with row_counts=NOT_RUN")
    generations = {MONTH_FILE: trip_generation, ZONE_FILE: zone_generation}
    for filename, generation in generations.items():
        if not generation.isdigit() or int(generation) <= 0:
            raise StagingManifestError(f"GCS generation for {filename} must be a positive integer")

    files: dict[str, dict[str, Any]] = {}
    for entry in source_manifest.get("files", []):
        if not isinstance(entry, dict):
            raise StagingManifestError("local manifest files entries must be JSON objects")
        name = entry.get("name")
        if name not in generations or name in files:
            raise StagingManifestError(f"unexpected or duplicate staged filename: {name!r}")
        expected_url = MONTH_URL if name == MONTH_FILE else ZONE_URL
        if entry.get("source_url") != expected_url:
            raise StagingManifestError(f"unexpected official source URL for {name}")
        local_path = Path(str(entry.get("local_path", ""))).expanduser()
        if not local_path.is_file() or local_path.stat().st_size <= 0:
            raise StagingManifestError(f"local source file missing or empty: {name}")
        size = local_path.stat().st_size
        sha256 = _sha256(local_path)
        if int(entry.get("bytes", -1)) != size or entry.get("sha256") != sha256:
            raise StagingManifestError(f"local source receipt size/SHA-256 mismatch for {name}")
        files[name] = {
            "name": name,
            "source_url": expected_url,
            "bytes": size,
            "sha256": sha256,
            "generation": generations[name],
            "row_count": "NOT_RUN",
        }
    if set(files) != set(generations):
        raise StagingManifestError("the local manifest must contain exactly January Parquet and zone CSV")

    return {
        "status": "COMPLETE",
        "schema_period": "2024-01 through 2024-01",
        "row_counts": "NOT_RUN",
        "files": [files[MONTH_FILE], files[ZONE_FILE]],
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--trip-generation", required=True)
    parser.add_argument("--zone-generation", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        source = json.loads(args.source_manifest.expanduser().read_text(encoding="utf-8"))
        result = build_manifest(
            source,
            trip_generation=args.trip_generation,
            zone_generation=args.zone_generation,
        )
    except (OSError, json.JSONDecodeError, StagingManifestError) as exc:
        parser.error(str(exc))
    destination = args.output.expanduser().resolve()
    _write_atomic(destination, result)
    print(json.dumps({"status": result["status"], "output": str(destination), "files": result["files"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
