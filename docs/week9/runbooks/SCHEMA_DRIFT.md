# SCHEMA_DRIFT

## Symptom and impact

The monitor compares `weather_landing` `INFORMATION_SCHEMA.COLUMNS` with [`contracts/weather_landing.v1.yaml`](../../../contracts/weather_landing.v1.yaml). `G1.LANDING.SCHEMA` is P1 for a missing required field, type change, or unexpected required addition. `G1.LANDING.SCHEMA_ADDITIVE` is P2 for a new nullable field; it warns and may publish. G0 API schema failures are a separate producer-boundary check.

P1 routes to Slack plus the existing C9 Monitoring email channel when enabled. P2 routes to Slack. Schema monitor events contain column names and types only, not row values.

## Triage

1. Confirm the event's dataset is `w9_drill` or an approved `dbt_ci_pr_*`.
2. Review the structured event's `check_id`, missing/type-change/extra-column summary, `run_id`, and date.
3. Inspect only schema metadata. Replace `<isolated_dataset>` with the exact approved dataset identifier from the event; do not use a production dataset.

```sql
SELECT column_name, data_type, is_nullable, ordinal_position
FROM `dataforge-p7-lab-d0f725.<isolated_dataset>.INFORMATION_SCHEMA.COLUMNS`
WHERE table_name = 'weather_landing'
ORDER BY ordinal_position;
```

4. Compare the result with the ODCS contract and the producer schema. Do not dump records to debug a schema-only event.

If the metadata query returns no rows, the isolated landing table is absent or not populated. Treat schema status as **UNVERIFIED/setup incomplete**, not as proof of drift; create no table or alert as part of triage.

## Decision

- **Required field removed, type changed, or required field added:** stop publish and fix the producer or roll back the incompatible schema change. Do not auto-alter the landing table or weaken the gate.
- **Nullable field added:** if it is expected, review its meaning and classification, update the ODCS contract and downstream model metadata under normal review, and record the additive change. If unexpected, fix the producer. Keep the P2 warning until reconciliation is complete.
- **After correction:** rerun the schema gate/monitor on the same approved isolated dataset before reopening downstream publish.
- **Schema matches the approved contract:** do nothing after recording the evidence. A clean schema monitor pass is not an alert.
- **Backfill needed:** only backfill an approved isolated date range after the contract and producer agree. Preserve the existing grain and idempotency behavior.
- **Quarantined batch:** release only after correction and a fresh passing gate; the local harness procedure is [`quarantine-release.md`](quarantine-release.md).

## Escalation and rollback

Escalate breaking changes to the source owner, contract owner, and W9 integrator before editing the contract. Roll back the producer/schema change if it is incompatible with current consumers; do not drop columns or overwrite last-good data to make a check pass. No live DDL or production write is authorized by this runbook.

For a controlled drift drill, retain the injection and detection timestamps for MTTD measurement. No live alert receipt is claimed.
