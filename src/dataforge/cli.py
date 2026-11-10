"""Small, AI-independent CLI; every operation is explicit and local-first."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="dataforge", description="DataForge local-first DE lab")
    sub = parser.add_subparsers(dest="command", required=True)
    g = sub.add_parser("generate", help="Create deterministic synthetic Vietnam commerce CSVs")
    g.add_argument("--orders", type=int, default=3000)
    g.add_argument("--seed", type=int, default=42)
    ing = sub.add_parser("ingest", help="Validate CSV and materialize content-addressed Parquet")
    ing.add_argument("--source-dir", type=Path, default=None)
    ing.add_argument("--sources", nargs="+", default=None)
    w = sub.add_parser("weather-fetch", help="Explicit opt-in real Open-Meteo HTTP requests")
    w.add_argument("--start", type=date.fromisoformat, required=True)
    w.add_argument("--end", type=date.fromisoformat, required=True)
    w.add_argument("--province", nargs="+", choices=["HCM", "HN", "DN"], default=None)
    p = sub.add_parser("profile-external", help="Inspect third-party CSV headers without mapping")
    p.add_argument("--dir", type=Path, required=True)
    p.add_argument("--output", type=Path, default=Path("docs/external_profile.json"))
    sub.add_parser("reference-metrics", help="Independent Decimal/CSV oracle for synthetic demo")
    cpre = sub.add_parser(
        "cloud-preflight",
        help="Verify one active synthetic Parquet snapshot without network or cloud credentials",
    )
    cpre.add_argument("--source", required=True)
    cpre.add_argument("--manifest-dir", type=Path, default=None)
    cpre.add_argument("--bronze-root", type=Path, default=None)
    cpre.add_argument("--region", default="us-central1")
    ctransfer = sub.add_parser(
        "cloud-transfer",
        help="Dry-run GCS upload and typed BigQuery staging; --execute opts into cloud writes",
    )
    ctransfer.add_argument("--source", required=True)
    ctransfer.add_argument("--project")
    ctransfer.add_argument(
        "--expected-project-number",
        help="Project number from the selected project; execute refuses a bucket owned elsewhere",
    )
    ctransfer.add_argument("--bucket")
    ctransfer.add_argument("--dataset", default="staging")
    ctransfer.add_argument("--region", default="us-central1")
    ctransfer.add_argument("--bucket-location")
    ctransfer.add_argument("--dataset-location")
    mode = ctransfer.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="execute", action="store_false",
                      help="Local-only preflight; this is the default")
    mode.add_argument("--execute", dest="execute", action="store_true",
                      help="Perform the GCS and BigQuery operations using ADC")
    ctransfer.set_defaults(execute=False)
    sub.add_parser("db-init", help="Create PostgreSQL schemas and raw tables")
    sub.add_parser("db-load", help="Transactionally merge changed Parquet source snapshots")
    sub.add_parser("db-build", help="Rebuild dimensional marts and analytics views")
    chk = sub.add_parser("db-check", help="Check raw FK, fact grain, SCD2, metric invariants")
    chk.add_argument("--synthetic", action="store_true", help="Enforce synthetic-fixture payment equality")
    q = sub.add_parser("query", help="Execute an allowlisted SQL analysis query")
    q.add_argument("name", help="e.g. q01_monthly_growth")
    args = parser.parse_args(argv)

    if args.command == "generate":
        from .generator import generate
        _print(generate(count=args.orders, seed=args.seed))
    elif args.command == "ingest":
        from .ingestion import ingest
        _print(ingest(source_dir=args.source_dir or __import__("dataforge.settings", fromlist=["SOURCE"]).SOURCE,
                      sources=args.sources))
    elif args.command == "reference-metrics":
        from .reference import reference_metrics
        _print(reference_metrics())
    elif args.command == "cloud-preflight":
        from .cloud.adapters import CloudAdapterError, load_validated_snapshot, preflight_snapshot
        from .settings import BRONZE, MANIFESTS
        try:
            snapshot = load_validated_snapshot(
                args.source,
                manifest_dir=args.manifest_dir or MANIFESTS,
                bronze_root=args.bronze_root or BRONZE,
            )
            _print(preflight_snapshot(snapshot, region=args.region))
        except (CloudAdapterError, ValueError, OSError) as exc:
            parser.error(str(exc))
    elif args.command == "cloud-transfer":
        from .cloud.adapters import (
            CloudAdapterError,
            load_validated_snapshot,
            preflight_snapshot,
            transfer_snapshot,
        )
        from .cloud.google_cloud import GoogleCloudBackend
        from .settings import BRONZE, MANIFESTS
        try:
            snapshot = load_validated_snapshot(args.source, manifest_dir=MANIFESTS,
                                               bronze_root=BRONZE)
            if not args.execute:
                _print(preflight_snapshot(
                    snapshot,
                    project_id=args.project,
                    expected_project_number=args.expected_project_number,
                    bucket=args.bucket,
                    dataset=args.dataset,
                    region=args.region,
                    bucket_location=args.bucket_location,
                    dataset_location=args.dataset_location,
                ))
            else:
                if not args.project or not args.expected_project_number or not args.bucket:
                    parser.error(
                        "--execute requires --project, --expected-project-number, and --bucket"
                    )
                backend = GoogleCloudBackend(args.project)
                _print(asdict(transfer_snapshot(
                    snapshot,
                    backend,
                    project_id=args.project,
                    expected_project_number=args.expected_project_number,
                    bucket=args.bucket,
                    dataset=args.dataset,
                    region=args.region,
                )))
        except CloudAdapterError as exc:
            parser.error(str(exc))
    elif args.command == "weather-fetch":
        from .weather import fetch
        _print({"api_rows": fetch(args.start, args.end, args.province)})
    elif args.command == "profile-external":
        from .profile import profile
        _print({"files": profile(args.dir, args.output).keys(), "report": str(args.output)})
    elif args.command in {"db-init", "db-load", "db-build", "db-check", "query"}:
        from . import database
        if args.command == "db-init":
            database.init()
            print("schema created")
        elif args.command == "db-load":
            _print(database.load())
        elif args.command == "db-build":
            database.build()
            print("marts built")
        elif args.command == "db-check":
            _print(database.check(synthetic=args.synthetic))
        else:
            _print(database.query(args.name))


if __name__ == "__main__":
    main()
