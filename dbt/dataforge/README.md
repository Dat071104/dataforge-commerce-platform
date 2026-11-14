# DataForge Week 7 dbt project

This dbt project contains the accepted Week-5 transformations and the separate
P7.4.1 Mini-project 3 weather domain. The Week-5 publisher remains unchanged.
The weather models and publisher were run against the approved GCP project as
part of the bounded live syllabus demonstration; see the closure receipts under
`docs/cloud/week7/closure/`.

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

Do not run `dbt build` or default `dbt docs generate` with the offline target:
those commands can execute warehouse operations and the offline project is
intentionally invalid. A credential-free static docs artifact can be generated
from the parsed manifest without compiling or querying the warehouse:

```powershell
dbt parse --project-dir . --profiles-dir . --target offline
dbt docs generate --no-compile --empty-catalog --static --project-dir . --profiles-dir . --target offline
```

This produces a static site with manifest-based model/exposure lineage and an
empty `catalog.json`; it does not include warehouse column metadata and does
not publish the site to GitHub Pages. Use the trusted read-only CI identity
only if warehouse metadata is needed. The generated `target/`, logs, packages,
and profile are ignored.

## Mini-project 3 weather domain

The separate `weather_mini3` source is the typed landing relation
`weather_mini3.weather_landing`. Its physical request grain is
`(request_id, province_id, observation_date)`; request IDs are content hashes,
so identical replays share one identity and revised provider responses create
a new identity. The conformed incremental Silver grain is
`(province_id, observation_date, source, model)`, retaining the selected
request ID, source hash, exact manifest URI/generation, and `landed_at`. A later
manifest generation supersedes the older provider version for that key.

`fct_mini3_weather_daily` is the typed Gold candidate in
`dbt_weather_mini3`. It preserves millimetres and Celsius, retains null metrics
as unknown, and adds a three-state precipitation classification. It does not
join weather to the commerce or payment models. `dbt build` only builds and
tests this candidate; it does not publish it. After a successful build/test,
the separate `publish_weather_mini3` operation checks source and candidate
coverage, key uniqueness, allowed metric values, provenance, row parity and a
stable SHA-256 before an atomic version/pointer transaction into
`gold_weather_mini3`. The stable published relation is
`gold_weather_mini3.published_weather_daily`; publication uses its own pointer,
independent of the Week-7 order/payment pointer.

Use only the opt-in `weather_prod` target for the finite Cloud Run dbt job;
`weather_dev` is the same bounded target for an authorized local proof, and
`weather_full` writes the parity comparison to a separate dataset. Credential-
free dbt parsing remains the `offline` target:

```powershell
dbt parse --project-dir . --profiles-dir . --target offline

$env:DBT_DATAFORGE_PROJECT_ID = 'dataforge-p7-lab-d0f725'
$env:DBT_DATAFORGE_LOCATION = 'us-central1'
dbt build --project-dir . --profiles-dir . --target weather_dev --select tag:weather_mini3
dbt build --full-refresh --project-dir . --profiles-dir . --target weather_full --select tag:weather_mini3
dbt run-operation publish_weather_mini3 --project-dir . --profiles-dir . --target weather_prod `
  --args '{"workflow_run_id":"airflow-<64-character-run-hash>"}'
```

The publisher refuses a different project/dataset, empty or incomplete
three-province dates, invalid source provenance, duplicate grain, invalid
metrics, and any divergence between candidate Gold and Silver. The previous
publication stays current if those checks or the transaction fail. Do not run
the publish operation before the corresponding candidate build and its dbt
tests complete.

## Isolated SCD2 history proof

`week7_scd2_proof_history` is a separate timestamp snapshot over one synthetic
row in `dbt_scd2_proof_input`, with snapshot history in
`dbt_scd2_proof_history`. It is not a copy of or write to the Week-5 Silver
table. The guarded runner refuses to replace either table if it already exists,
requires both reviewed datasets in `us-central1`, and caps each BigQuery query
at 32 MiB. This accommodates BigQuery's 20 MiB minimum estimate for the proof
snapshot query while keeping the synthetic workload bounded. Start with a
read-only plan, then opt in only after checking project,
IAM, expiration, and cost:

```powershell
python .\scripts\run_scd2_history_proof.py
python .\scripts\run_scd2_history_proof.py --execute
```

The proof observes an initial `CREATED` state, a later `PROCESSING` state, then
a soft-delete `CANCELLED` tombstone. It snapshots after each change and once
more with unchanged input. It accepts only three non-overlapping versions, one
open current interval, and no fourth version on replay. Snapshot validity
timestamps reflect when dbt observed each source `updated_at`; they do not
reconstruct business-effective history, nor changes that happened and were
overwritten between snapshot runs. The live proof receipt is
[`dbt_scd2_history_receipt.json`](../../docs/cloud/week7/closure/dbt_scd2_history_receipt.json).
It records three observed versions, validity checks, the tombstone, and the
unchanged replay result. This synthetic proof does not modify authoritative
Week-5 history.
