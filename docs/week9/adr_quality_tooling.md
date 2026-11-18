# ADR: Week 9 quality tooling

Status: Draft — D-2 selected Great Expectations Core 1.25.0 from the paired temporary local spikes; controller G-A returned GO. The criteria below were written before measurement. This ADR is owned by the Week 9 integrator.

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

Both spikes used the same immutable seven-date local Parquet slice. Evidence level is temporary local spike only; this is not CI or live BigQuery connector evidence. After G-A, the integrator independently timed five clean Soda CLI verifications and sampled the full process tree; the runtime methods differ from GX in-process validation timing and are not a direct apples-to-apples comparison.

| Criterion | Soda Core v4.31.0 | Great Expectations Core 1.25.0 |
|---|---|---|
| License | PyPI says Proprietary; upstream LICENSE is Elastic License 2.0 | Apache-2.0 |
| Same five checks | Clean 5/5; F06 isolated volume fault failed only the expected check | Clean 5/5; all five isolated mutations were detected |
| LOC | 60 nonblank contract-check lines; no standalone runner | 263 nonblank, noncomment Python lines |
| Runtime | Integrator post-G-A: 2.7039 s median / 4.3044 s max over five clean Soda CLI verifications; separate agent contract-test-plus-verify run was 4.646 s | 0.2857 s median / 0.3367 s max over five GX validation runs, excluding Parquet load |
| Peak RSS | Integrator process-tree sample: 100.7 MiB maximum during Soda CLI verify (20-ms sampling) | 215.6 MiB |
| Install footprint | 84.62 MiB site-packages | 406.3 MiB site-packages |
| BigQuery support | Official v4 docs list soda-bigquery and ADC; not live-tested | Official docs support BigQuery and the bigquery extra; not live-tested; upstream docs tests temporarily skipped |
| Error detail | F06 names the check and threshold but omits date and observed count; schema required an information_schema workaround | Schema, row-count, and freshness failures lack detail without a wrapper; duplicate/range include counts |
| CI fit | Local DuckDB CLI returned exit 0/1; Linux CI not measured | Local Pandas checks return exit 0/1; Linux CI not measured |
| dbt overlap | Landing rules overlap conceptually with downstream dbt grain/range/freshness | Same ownership boundary; G1 owns landing, dbt remains downstream defense |

Official sources: Soda PyPI metadata https://pypi.org/project/soda-core/4.31.0/; Soda license https://github.com/sodadata/soda-core/blob/main/LICENSE; Soda BigQuery docs https://docs.soda.io/soda-v4/reference/data-source-reference-for-soda-core/bigquery; GX compatibility https://docs.greatexpectations.io/docs/help/compatibility_reference/; GX BigQuery install extra https://docs.greatexpectations.io/docs/core/set_up_a_gx_environment/install_additional_dependencies/; GX Apache-2.0 license https://github.com/fivetran/great_expectations/blob/develop/LICENSE.

Decision: choose Great Expectations Core 1.25.0 for G1. Apache-2.0 is a better fit for this public MIT repository. GX passed all five clean checks and detected all five isolated mutations; its validation median was 0.2857 seconds with 215.6-MiB peak RSS. The Soda CLI timing includes process startup, so runtime numbers are not directly comparable. The 406.3-MiB package footprint and 263 LOC are accepted costs. The G1 runner must wrap GX failures with check_id, date, severity, threshold, and action because raw schema, row-count, and freshness messages lack enough triage context.

Soda Core v4.31.0 is not selected because its current PyPI metadata is Proprietary and its upstream license is ELv2 for this public repository. Its built-in schema check returned NOT_EVALUATED for the file-backed DuckDB source, the documented group_by type was rejected, and two metric checks needed distinct qualifiers. Soda Core v3.5.6 is a legacy alternative; it was not installed or measured. The Windows verification also emitted UnicodeEncodeError logging traces under cp1252 despite the expected clean/F06 exit codes; Linux CI behavior was not measured.

BigQuery support for both products is documented but was not live-tested. GX Core's upstream changelog says BigQuery backend tests are temporarily skipped; W9-2 must verify the connector using a read-only, isolated-dataset smoke test. Do not claim live BigQuery support until that passes.
## Adjacent decisions

| Decision | Current approved direction | Evidence still required |
|---|---|---|
| D-3 Catalog | Trimmed OpenMetadata in CI plus time-boxed Dataplex / BigQuery lineage | Measure OpenMetadata memory and CI duration; capture lineage evidence |
| D-4 Slack | Runner webhook; Monitoring email remains the independent route | User supplies webhook; live drill receipt remains pending |
| D-5 Pseudonymization | HMAC-SHA256 in Python; key from Secret Manager | Synthetic-only implementation and access tests |
| D-6 Missing province | Block the entire date | F06 fixture and unchanged Gold hash |

## Revisit triggers

Revisit D-2 if GX cannot run keylessly against BigQuery, exceeds the workflow timeout or memory budget, or remains ambiguous after the runner wrapper. Revisit D-0 if the CLI fails to lint the pinned ODCS version or becomes incompatible with the repository Python/toolbox lock.

Decision log: D-2 selected GX from the paired temporary local spike; controller gate G-A returned GO. Evidence level: implemented ADR decision plus local spike; no CI/Linux or live-GCP connector result is claimed.
