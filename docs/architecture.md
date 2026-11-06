# Architecture Decision Record — Baseline

## Objectives

Combine two intern syllabus deliverables into one local-first Vietnamese commerce reference while avoiding premature enterprise platform design. System of record: synthetic CSV source; auxiliary weather via API (optional). Analytical storage: PostgreSQL. Reporting: Power BI Desktop.

## Diagrams

- [`diagrams/architecture.mmd`](diagrams/architecture.mmd) — sources through Bronze, PostgreSQL and the Power BI snapshot export.
- [`diagrams/star_schema.mmd`](diagrams/star_schema.mmd) — Gold fact grains, dimension keys and active/inactive date roles.

## Data flow

`data/source/*.csv` -> validate (fail-closed) -> content-addressed Parquet in `data/bronze/{table}/sha256={hash}/part-000.parquet` -> write `data/manifests/runs/{run_id}.json`, then atomically replace the single `data/manifests/active.json` pointer -> transactional changed-source snapshot merges into `raw.*` -> transactional dimension maintenance and full fact rebuild in `dw.*` -> `analytics.*` -> read-only Gold snapshot export (`scripts/export_powerbi_gold.py`) -> Power BI Desktop Import model.

Bronze snapshots are content-addressed; identical source bytes reuse the same path. Changed input gets a new hash path; retention/cleanup is unimplemented. A run ID is a UUID hex string. `active.json` contains only that `run_id` and points to its run record under `runs/`.

Each source record stores both the source CSV digest (`source_sha256`) and the digest of the actual Parquet bytes (`bronze_sha256`), plus the validated column order and row count. The generator only rewrites an existing source set when its marker identifies synthetic data and every existing CSV matches the recorded hash. Weather API responses must contain the exact requested inclusive daily date sequence for each province; bad coverage is rejected before source files are changed.

## Ingestion manifest and promotion

- Each `dataforge ingest` invocation creates a `running` record at `data/manifests/runs/{run_id}.json`. It validates every selected CSV before adding it to that run's prepared source map. Parquet bytes are written to a temporary file and atomically renamed into their content-addressed path; the resulting byte digest, column order and row count are stored in the run record.
- On success, the run record is atomically replaced with `status="complete"` and a `sources` map. The map is the full manifest snapshot for the run: prior active sources (if an active pointer exists) merged with the newly ingested sources. Thus a subset run preserves earlier source entries. On a workspace with no active pointer, existing per-source manifests seed this map when available. `previous_run_id` links to the prior active run, or is null when upgrading from legacy manifests/no prior run.
- The completed run record is written before `active.json` is atomically replaced. JSON publication uses a temporary file in the same directory, flushes and syncs it, then calls `os.replace`; readers therefore see the prior pointer or the new pointer, not a partially written pointer. A validation, Parquet-write, completed-record-write or pointer-replacement failure records a failed run where possible and leaves the prior pointer unchanged (or leaves `active.json` absent if there was no prior active run). Already written content-addressed Parquet and failed run records can remain; cleanup is not implemented.
- After pointer promotion, per-source `{source}.json` files are refreshed as **best-effort compatibility mirrors**. A mirror-write warning does not invalidate the committed active run. Once `active.json` exists, mirrors are not authoritative.
- A first subset run with no prior or legacy manifests can be marked complete while its `sources` map still lacks configured sources. `database.load` requires the exact configured source set, so this partial snapshot is not loadable until all required sources are present.
- Concurrent `ingest` invocations are not serialized and do not use compare-and-swap. If two runs read the same prior pointer and publish overlapping or different subsets concurrently, whichever pointer replacement happens last wins; the later run can omit the other run's newly ingested sources. Run sequentially when source subsets are being updated.

`database.load` resolves and validates the manifest set before opening a database connection. If `active.json` exists, it follows that pointer and requires a matching run ID, a complete run status, the exact expected source set, matching source names, valid source and Parquet digests, and a recorded positive row count. It hashes and parses the exact Parquet bytes, checking schema and count, before connecting; it repeats the verification when staging changed snapshots. A modified or truncated artifact therefore fails before raw-table mutation. A malformed or incomplete active pointer fails closed; it does **not** fall back to per-source mirrors. Only when `active.json` is absent does `database.load` use the legacy `{source}.json` manifests. Legacy manifests without a Parquet digest cannot be loaded directly: run full `dataforge ingest`, which validates each current CSV and only upgrades an existing legacy Parquet file if its bytes match the deterministic serialization of that CSV. If a legacy artifact differs, preserve it and recover from a trusted copy rather than overwriting it.

For Open-Meteo weather, ingestion requires the current CSV digest to agree with both `_DATAFORGE_SOURCE.json` and a complete `weather_provenance.json` sidecar, including its row count. Fetch stages the CSV, marker, sidecar and raw responses before promotion, promotes the CSV last, and restores the prior three source/provenance files on a caught write failure. A process interruption can still leave a mixed set; the prior files are backed up under `.open_meteo/transactions/{transaction_id}/` with a hash/presence manifest. Ingestion fails closed until the prior set is restored or the explicit fetch is repeated after reviewing provider terms.

## P4 database load and mart lifecycle

- There is no trusted event-date watermark. `database.load` compares each active source hash with the latest hash in `audit.load_runs`. If the hash is unchanged, that source skips Parquet staging and raw/audit DML. If it changed, the Parquet file is treated as the authoritative **complete snapshot** for that source; row absences mean deletes, rather than requiring separate tombstone events.
- All changed source snapshots are copied to temporary tables with the configured primary-key constraints before any raw table is modified. In one PostgreSQL transaction, each changed snapshot updates rows whose non-key values differ, inserts new primary keys, deletes target keys absent from the snapshot, and records `rows_inserted`, `rows_updated`, and `rows_deleted` in `audit.load_runs` (`operation="snapshot_merge"`). A duplicate key, schema/COPY error, or failed reference check rolls back the whole changed-source batch and its audit writes. Empty CSV/Parquet snapshots are rejected by validation.
- Before that raw-load transaction commits, the loader checks cross-table references/orphans and customer SCD2 invariants: one current segment per customer matching the current customer row, exactly one segment valid on each order date, and no overlapping validity ranges. These are explicit checks in the loader; the raw schema does not declare relational foreign-key constraints.
- `database.build` runs the mart SQL in a separate transaction. Existing product (`product_id`), geography (`province_id`) and customer-version (`customer_id`, `valid_from`) rows retain their surrogate keys when the natural key remains present. Missing natural keys are deleted from the corresponding dimension; later reintroduction receives a new surrogate key. `audit.dimension_key_state` seeds from existing dimension maxima, maintains monotonic high-water marks, and is locked with `FOR UPDATE` during builds so a deleted key is not reused. Preserve this state table. The date dimension uses its deterministic natural `YYYYMMDD` key rather than this high-water allocator.
- Each `db-build` transaction truncates and repopulates every fact table from the current raw snapshot, then refreshes the analytics views. Facts are still full-rebuilt; they are not incrementally merged. Raw loading and mart building remain separate transactions, so a successful `db-load` followed by a failed `db-build` leaves new raw data committed and the prior mart build intact.
- Dimension-key locks serialize key allocation between builds; there is no pipeline-wide lock. The P1 concurrent-ingest limitation remains: concurrent manifest publications are last-writer-wins, so serialize subset ingestion to avoid one run omitting another's changes.

## Grain register

| Object | Exactly one row per | Primary key |
|---|---|---|
| raw.orders | order | order_id |
| raw.order_items | order line | order_item_id |
| raw.payments | payment event | payment_id |
| raw.returns | return event | return_id |
| raw.shipments | shipment event | shipment_id |
| raw.inventory | product/month snapshot | snapshot_date+product_id |
| dw.dim_customer | customer SCD2 version | customer_key |
| dw.fct_order_item | order line | order_item_id |
| dw.fct_payment | payment | payment_id |
| dw.fct_return | return | return_id |
| dw.fct_shipment | shipment | shipment_id |
| dw.fct_inventory_snapshot | product/date | snapshot_date_key+product_key |
| dw.fct_weather_daily | province/day | geography_key+date_key |

## SCD2

- Synthetic `customer_segments` includes validity ranges: start inclusive, end exclusive.
- Every order resolves to exactly one customer version valid on `order_date`.
- SCD2 change history in real source must be evidenced by source change events; current-state tables alone cannot reconstruct true history. Do not manufacture history except explicitly labeled test fixtures.

## Reliability

- Python validation fails closed and quarantines invalid rows. The active-run pointer provides atomic manifest-set promotion for ingestion; this is a filesystem pointer swap, not a transaction across all Parquet files or PostgreSQL. Parquet digests provide integrity checks against the active manifest, not signatures against an actor who can rewrite both.
- Changed-hash full-snapshot merges into raw tables and their audit deltas run in a single transaction; failure rolls back the batch. Identical source hashes skip raw/audit DML.
- Dimension maintenance, monotonic surrogate-key state and full fact/view rebuild run in a separate transaction; build failure rolls back that mart transaction.
- There is a **gap** between active manifest promotion, the raw-load transaction and the mart-build transaction. Full atomic promotion across files, raw tables and marts has not been implemented.
- No long-running orchestration, metrics exporter, alert pipeline or SLA in baseline.

## CI

`.github/workflows/ci.yml` is configured for `push` and `pull_request`. It installs from `requirements-py311.lock`, starts a disposable PostgreSQL 16 service with a health check, exposes it on the runner at `127.0.0.1:5432`, runs Ruff, compileall, `pip check`, offline and PostgreSQL-enabled suites (including `dashboards/P5/tests`), then prepares the seed-42 Gold workbook and runs the PBIP validator. The `postgres` service user can create the unique temporary databases used by integration tests. The local workflow file and commands are checked; a remote GitHub Actions run is not claimed.

## Metric semantics

`gross_item_value=quantity*unit_price`; `discount_value=gross*discount_pct`; `net_order_value=gross-discount`; `fulfilled_sales_proxy=net_order_value IF status='delivered'`; `fulfilled_cogs_proxy=qty*product.unit_cogs IF delivered`; `collected_amount=payment.amount IF status='success'`; `completed_refund=refund_amount IF return.status='completed'`.

Analytics order reconciliation *first* aggregates line, payment and refund facts separately by order ID before joining. Refund occurrence date differs from original order date; do not subtract date-series without choosing reporting convention.

## Risks / trade-offs

- Single local PostgreSQL is enough at this scale and fast to iterate; not a production SLA.
- Stable product, geography and customer-version keys depend on retaining `audit.dimension_key_state`; do not reset or drop it. Dimensions still remove natural keys missing from the authoritative snapshot, while fact tables are rebuilt each time.
- Power BI Import creates fast interactive reports on small data; refresh is manual in baseline.
- Cloud Run **Jobs**, not an always-on HTTP service, are the planned container fit for finite ingestion steps; database/warehouse design requires a separate cloud migration.
