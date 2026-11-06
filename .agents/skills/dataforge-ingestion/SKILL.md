---
name: dataforge-ingestion
description: Build, review or troubleshoot DataForge CSV/API ingestion, validation, Parquet snapshots, manifests and reproducible backfills.
---

# Ingestion workflow

1. Read `src/dataforge/{generator,ingestion,weather,cli}.py` and `configs/sources.csv`; read only task-relevant docs.
2. Lock source schema, column meanings, primary key and time semantics before modifying transformations.
3. Preserve raw bytes or source provenance. Use checksum-based content-addressed bronze, typed validation, clear errors and quarantine. Never silently drop broken rows.
4. Explicit retries only for transient HTTP errors, bounded timeouts; respect API rate and license; do not fetch network without permission.
5. Test: duplicate key, null key, schema drift, negative money, discount range, API timeout, repeat import, malformed date and deterministic seed.
6. Report observed evidence and artifact paths. Do not claim end-to-end PostgreSQL success from Python-only tests.
