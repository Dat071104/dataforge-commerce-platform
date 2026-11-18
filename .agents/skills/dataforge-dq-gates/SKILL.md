---
name: dataforge-dq-gates
description: Design, implement or review DataForge data-quality gates (G0 ingest contract, G1 boundary checks, G2 dbt tests), test tiers, dq_results logging and Write-Audit-Publish/quarantine behaviour.
---

# Data-quality gates (Week 9)

1. Read the contract in `contracts/` and the catalog `docs/week9/failure_modes.md` first. Every check maps to exactly one check ID and one owning layer. Never add a second tool that checks the same rule.
2. Layers: **G0** = Python ingest validation (payload shape, units, requested vs returned dates, HTTP 200 with empty data). **G1** = boundary checks on landing before dbt (schema, row_count per date, missing/duplicate/invalid, physical ranges, freshness). **G2** = dbt tests + model contracts on silver/gold. Prefer deterministic expectations (3 provinces per date) over anomaly detection.
3. Severity lives in config, not prose: P1 blocks publish and quarantines; P2 warns and publishes; P3 records only. dbt: `tags: [tier_blocking]` or `[tier_advisory]`, `severity`, `error_if`, `warn_if`. Every gate honours `DQ_ENFORCE=warn|block` (shadow mode first).
4. Test the tests: each blocking check ships with one fixture that makes it fail and one that passes. A check without a failing fixture is not done.
5. FLOAT64 comparisons use the shared tolerance macro (lesson from PR #39). Never exact equality on floats.
6. Every gate run writes rows to `dataforge_dq.dq_results` (`run_id, check_id, layer, severity, status, observed, threshold, failing_rows, contract_version, ts`). dbt uses `store_failures` into `dataforge_dq`.
7. Write-Audit-Publish: on P1 the published Gold must be identical before and after (assert a table hash), and the batch manifest moves to `quarantine/<run_id>/` with a reason. Stale-but-correct beats fresh-but-wrong.
8. Drills and tests never point at prod datasets (`weather_mini3`, `dbt_weather_mini3`, `silver`, `ops`, `gold`). Use `DBT_WEATHER_LANDING_SCHEMA` and an isolated dataset (`w9_drill`, `dbt_ci_pr_<n>`).
9. Report: check IDs added, fixture paths, commands, pass/fail counts, CI run ID, evidence level.
