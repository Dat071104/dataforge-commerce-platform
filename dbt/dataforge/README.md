# DataForge Week 7 dbt project

This project is a candidate BigQuery transformation layer over the already
published Week-5 Silver tables and operational ledger. It does not replace the
Week-5 atomic publisher and has not been run against GCP as part of local
development.

## Models and grains

- `stg_week5_orders`: one current Silver row per `order_id`, including soft
  tombstones.
- `stg_week5_payment_events`: one current Silver row per `payment_id`, including
  soft tombstones.
- `int_week5_active_orders`: one non-deleted order per `order_id`.
- `int_week5_current_payments`: one current payment state per `payment_id`; a
  deleted payment remains visible with `is_deleted = true`.
- `int_week5_successful_collections_by_order`: one row per order with the sum of
  active successful payment events. Payment facts are aggregated before any
  order-level join.
- `int_week5_delivered_sales_proxy_by_order`: one row per order. The amount is
  zero for non-delivered or deleted orders. This is an analytics proxy, not
  accounting-recognized revenue.
- `fct_week7_order_reconciliation`: one current row per order. Deleted orders
  keep successful collections visible, have zero delivered-sales proxy, and
  have a null collection variance. Payment tombstones no longer contribute to
  collections.
- `int_week7_batch_control`: one operational quality/control row per Week-5
  `run_id`, derived from `ops.week5_run_events` and the current checkpoint.
- Singular tests compare the candidate's order controls to the atomic
  `gold.week5_order_controls` table on the same current snapshot, including
  tombstoned orders; active payments must reference an order while payment
  tombstones are exempt from that relationship test.
- `week5_orders_history` snapshot: SCD2 history of the observed Silver order
  state keyed by `order_id`; validity timestamps reflect Silver ingestion
  observations, not business-effective dates, and multiple changes between
  snapshot runs can be coalesced.

The reconciliation mart uses `effective_seq`, not event timestamps, to find
source changes. Its payment watermark includes tombstones. When a payment moves
to another order, the previous order's saved payment watermark no longer
matches its current aggregate, so both old and new order keys are recomputed.
The model uses BigQuery `MERGE` with a stable integer range partition derived
from the order key; date corrections therefore do not move a key to another
partition. The bucket predicate is a correctness-preserving bound on the merge
target. Query bytes and actual partition pruning still require a live BigQuery
job receipt; this project makes no measured cost or performance claim.

Accepted order (`delivered`, `processing`) and payment (`success`, `failed`)
values in the schema tests reflect the deterministic Week-5 simulator cases.
The Week-5 source change contract does not define a broader business status
enum, so these values must not be presented as exhaustive for other datasets.

If source quality blocks the reconciliation model, the incremental query emits
no source rows and therefore leaves previously materialized rows intact. The
attached `dbt build` test then fails the run. This is a data-layer safety gate,
not a cross-table transaction or a replacement for the Week-5 publication
pointer.

## Local setup and offline validation

Python 3.11 is supported by the parent repository. From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item profiles.example.yml profiles.yml
$env:DBT_PROFILES_DIR = (Get-Location).Path
dbt parse --project-dir . --profiles-dir . --target offline
```

The `offline` profile has no key or token and points to a deliberately
non-existent project. `dbt parse` is the credential-free local check. This
BigQuery adapter can still open a warehouse connection for `dbt compile`, even
with `--no-introspect`; the CI compile job uses a constrained, keyless GitHub
OIDC identity on trusted upstream branch pushes. Pull-request jobs, including
fork PRs, receive no GCP identity. Use the `dev` target locally only after
explicit authorization, ADC setup, and verification of the approved project,
dataset, region, IAM, and query budget. Use the `full` target for a clean
full-refresh comparison; it writes to the separate `dbt_week7_full` dataset
and is not a publication target.

```powershell
$env:DBT_DATAFORGE_PROJECT_ID = '<approved-project-id>'
$env:DBT_DATAFORGE_TARGET_DATASET = 'dbt_week7'
$env:DBT_DATAFORGE_FULL_REFRESH_DATASET = 'dbt_week7_full'
$env:DBT_DATAFORGE_GOLD_DATASET = 'gold_week7'
$env:DBT_DATAFORGE_LOCATION = 'us-central1'
dbt compile --project-dir . --profiles-dir . --target dev --no-introspect
dbt build --project-dir . --profiles-dir . --target dev
dbt docs generate --project-dir . --profiles-dir . --target dev
```

The workflow takes a bounded lease before building, verifies the candidate
build receipt and the source `PUBLISHED`/`CHECKED` record, then calls
`publish_week7`. That macro inserts an immutable run-version and compare-and-
sets the seeded `gold_week7.week7_publication_pointer` in one BigQuery
transaction. A failed assertion rolls back the transaction and leaves the old
pointer active. The workflow must skip publication when `acquire_week7_lock`
returns `OVERLAP_SKIPPED` and release an acquired lock in its cleanup path.
Lease expiry prevents an abandoned owner from publishing after a newer
workflow takes over.

```powershell
dbt run-operation acquire_week7_lock --project-dir . --profiles-dir . --target dev `
  --args '{"workflow_run_id":"wf-20261111-001","lease_seconds":3600,"batch_id":"<64-lowercase-hex>","manifest_generation":123,"upper_seq":20,"run_mode":"normal"}'
dbt build --project-dir . --profiles-dir . --target dev --vars `
  '{"workflow_run_id":"wf-20261111-001","batch_id":"<64-lowercase-hex>","manifest_generation":123,"upper_seq":20,"run_mode":"normal"}'
dbt run-operation publish_week7 --project-dir . --profiles-dir . --target dev --args `
  '{"workflow_run_id":"wf-20261111-001","batch_id":"<64-lowercase-hex>","manifest_generation":123,"upper_seq":20,"run_mode":"normal","test_fail_before_publish":false}'
dbt run-operation release_week7_lock --project-dir . --profiles-dir . --target dev `
  --args '{"workflow_run_id":"wf-20261111-001"}'
```

The controlled recovery drill may set `test_fail_before_publish=true` on the
`publish_week7` operation only. It fails after candidate validation, records a
redacted `INJECTED_FAILURE` ledger event, and rolls back before the version
insert or pointer update. Retry the same manifest with the flag set to false;
the Week-5 consumer should return `NO_OP` and dbt should publish the validated
candidate. A backfill can have `upper_seq` above the normal checkpoint; the
pointer stores both values, and later normal checkpoint progress remains
monotonic even when its sequence is numerically below an earlier backfill's
`upper_seq`.

`gold_week7.published_order_reconciliation` is a stable view over the immutable
run-version table and selects only the version named by the pointer. It is
created after the version table exists and continues to expose the prior run
while the next candidate is being validated.

Do not run `dbt build` or `dbt docs generate` with the offline target: those
commands execute warehouse operations and the offline project is intentionally
invalid. The generated `target/`, logs, packages, and profile are ignored.
