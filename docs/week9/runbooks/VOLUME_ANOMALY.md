# VOLUME_ANOMALY

## Symptom and impact

This event type has two meanings; use `check_id` and severity to distinguish them:

- `G1.LANDING.ROWS_PER_DATE` is P1 when the expected three province rows for a date are incomplete. It blocks that date and preserves the last-good Gold snapshot.
- `MONITOR.WEATHER.TEMP_DISTRIBUTION` is P2 when the 30-day temperature mean or standard-deviation signal exceeds 3 baseline standard deviations, with at least 20 observations in both windows. It warns and publishes.

Only P1/FAIL events receive the C9 Monitoring email policy. P1/P2 Slack routing is handled by the DQ runner. A clean F-N0 fixture should produce no alert.

## Triage

1. Record `check_id`, event date, severity, `failing_rows`, observed counts/scores, threshold, dataset, and publish status.
2. Confirm that the dataset is `w9_drill` or an approved `dbt_ci_pr_*`.
3. For a row-count failure, inspect aggregate keys only:

```sql
SELECT observation_date,
       COUNT(*) AS row_count,
       COUNT(DISTINCT province_id) AS province_count,
       ARRAY_AGG(DISTINCT province_id ORDER BY province_id) AS province_ids
FROM `dataforge-p7-lab-d0f725.<isolated_dataset>.weather_landing`
WHERE observation_date = @event_date
GROUP BY observation_date;
```

4. For a distribution warning, compare the event's baseline/recent counts and z-scores by province with the two 30-day windows. Use aggregates only; do not export raw rows into alerts or tickets.

## Decision

- **P1 incomplete date:** block the whole date; do not publish two of three provinces. Correct the upstream source or the ingestion gap, then run a bounded retry. Backfill only after all three expected province rows are available.
- **P2 distribution warning:** if the event reflects an expected weather shift or insufficient context despite the minimum sample gate, document and do nothing. If it reflects a source/unit defect, fix the producer or approved contract and rerun the isolated check.
- **Quarantine:** preserve the candidate and compare last-good hashes. Use [`quarantine-release.md`](quarantine-release.md) only for local WAP evidence; a live release needs separate approval.
- **Clean pass:** do nothing; retain the zero-alert negative-control result.

## Escalation and rollback

Escalate a P1 missing-province case to the source owner and integrator; escalate repeated P2 distribution warnings to the data owner within one business day. Never publish a partial daily population to clear the alert. If a false positive follows a code change, pause the run and revert the change after review. Restore the local last-good snapshot by its manifest hash if local WAP publication changed unexpectedly. No production write is authorized.

For a controlled fault injection, record injection and alert delivery times independently for MTTD. No live alert delivery is claimed.

## Drill restore and close-out

For the isolated `w9_drill` dataset, follow [drill-restore-and-closeout.md](drill-restore-and-closeout.md): it covers several alerts from one cause, missing vs. extra rows, restoring one date, and the required close-out (gate in block mode, then `monitor --since --send-alerts` to resolve).
