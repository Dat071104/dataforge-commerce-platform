"""Small, AI-independent CLI; every operation is explicit and local-first."""
from __future__ import annotations

import argparse
import json
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
