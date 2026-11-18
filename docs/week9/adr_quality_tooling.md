# ADR: Week 9 quality tooling

Status: Draft — selection of the landing quality engine is pending the paired Soda Core / Great Expectations (GX) spike. The criteria below were written before those measurements. This ADR is owned by the Week 9 integrator.

## Scope

Choose the tool for G1 landing checks and document adjacent tool ownership for contracts, G0 ingest validation, G2 dbt tests, and catalog/lineage. A tool may not own a second check already owned by another layer.

## Evaluation criteria

| Criterion | Measurement | Decision relevance |
|---|---|---|
| Lines of code for five identical checks | Count configuration and runner LOC | Lower setup and maintenance burden is better |
| Runtime | Median of five runs over the same seven-date slice | Must fit a PR job timeout with room for other gates |
| Peak RAM | Process peak working set during the same run | Must fit the Linux CI runner and the low-memory laptop constraints |
| Error-message quality | Record whether the failing rule, date, and observed value are clear without leaking row values | Triage must be actionable and safe |
| BigQuery support | Confirm connector and auth path from official docs; prove a read-only check | Required for live isolated-dataset evidence |
| License | Read the package license and dependency notices | Must be compatible with repository use |
| Install size | Measure installed distribution size in the toolbox environment | Keep CI and image footprint bounded |
| CI friendliness | Record deterministic exit code, machine-readable result, timeout behavior, and keyless auth fit | Required for exact-head PR gates |
| Overlap with dbt tests | Map each of the five checks to its owning layer | Avoid duplicate ownership and contradictory results |

## D-0 — ODCS contract lint

Decision: use `datacontract-cli==1.2.8` for structural linting of the ODCS contracts only. It validates contract syntax/schema; it does not own weather data checks and will not query BigQuery in lint. The current CLI documentation identifies ODCS v3.2.0 as its default and documents `datacontract lint`; the upstream CLI project is MIT licensed. This required validator is separate from the D-2 runtime G1 engine decision.

Sources: [Data Contract CLI ODCS docs](https://github.com/datacontract/datacontract-cli/blob/main/docs/docs/open-data-contract-standard.md), [CLI commands](https://cli.datacontract.com/commands), [CLI package metadata](https://github.com/datacontract/datacontract-cli/blob/main/pyproject.toml).

## D-2 — G1 landing quality engine

Candidates: Soda Core and Great Expectations Core. Decision is pending both spikes running the same five checks on the same immutable seven-date slice. No LOC, runtime, RAM, or error-quality measurements are claimed yet.

| Check | Planned owner |
|---|---|
| API response shape, requested date coverage, retry semantics | G0 Python validation |
| Landing schema, expected 3 rows/date, duplicates, allowed provinces, physical ranges, freshness | G1 — D-2 winner |
| Weather transform consistency and model grain | G2 dbt tests |
| Contract YAML structure | `datacontract lint` |
| Monitoring and alert delivery | Observability monitors read `dataforge_dq.dq_results`; they do not re-run gate logic |

## Adjacent decisions

| Decision | Current approved direction | Evidence still required |
|---|---|---|
| D-3 Catalog | Trimmed OpenMetadata in CI plus time-boxed Dataplex / BigQuery lineage | Measure OpenMetadata memory and CI duration; capture lineage evidence |
| D-4 Slack | Runner webhook; Monitoring email remains the independent route | User supplies webhook; live drill receipt remains pending |
| D-5 Pseudonymization | HMAC-SHA256 in Python; key from Secret Manager | Synthetic-only implementation and access tests |
| D-6 Missing province | Block the entire date | F06 fixture and unchanged Gold hash |

## Revisit triggers

Revisit D-2 if the selected tool cannot run keylessly against BigQuery, exceeds the workflow timeout or memory budget, gives ambiguous failures, or requires a second owner for an existing check. Revisit D-0 if the CLI fails to lint the pinned ODCS version or becomes incompatible with the repository Python/toolbox lock.

Decision log: pending paired spike results and controller gate G-A. Evidence level: implemented as an ADR draft; no runtime engine selection or live data check is claimed.
