# FRESHNESS_BREACH

## Symptom and impact

`G2.SOURCE.FRESHNESS` owns F07. The dbt source-freshness thresholds are **warn after 36 hours (P2)** and **error after 72 hours (P1)**. The `max(landed_at)` monitor value is context only; it must not become a second freshness threshold. P1 routes to Slack and C9 Monitoring email when enabled; P2 routes to Slack.

The W7 Airflow VM was intentionally torn down. Until an approved active schedule exists, keep the W9 freshness policy disabled (`enable_dq_freshness_alert=false`) and the dead-man policy disabled. The absence of new runs during an intentional stop is expected.

## Triage

1. Check whether the pipeline is active or inside a documented maintenance window. Confirm the event dataset is `w9_drill` or an approved `dbt_ci_pr_*`.
2. Inspect the latest source-freshness result without selecting raw rows:

```sql
SELECT ts, run_id, check_id, layer, severity, status, failing_rows, threshold
FROM `dataforge-p7-lab-d0f725.dataforge_dq.dq_results`
WHERE check_id = 'G2.SOURCE.FRESHNESS'
  AND JSON_VALUE(observed, '$.dataset') = @dataset
ORDER BY ts DESC
LIMIT 10;
```

3. For a live, authorized isolated run, compare source freshness `max_loaded_at` with the expected run window. `weather_landing.landed_at` can be inspected as context only:

```sql
SELECT MAX(landed_at) AS latest_landed_at,
       MAX(observation_date) AS latest_observation_date,
       COUNT(*) AS rows_in_window
FROM `dataforge-p7-lab-d0f725.<isolated_dataset>.weather_landing`
WHERE observation_date >= DATE_SUB(CURRENT_DATE('Asia/Ho_Chi_Minh'), INTERVAL 60 DAY);
```

4. Check upstream API/job status and the most recent bounded retry result. Do not repeatedly rerun an unchanged failing request.

## Decision

- **Expected stopped pipeline / maintenance window:** do nothing operationally; keep freshness and dead-man policies disabled. If policies were enabled before a planned pause, create a time-bounded [Cloud Monitoring snooze](https://docs.cloud.google.com/monitoring/alerts/snooze) for the exact policies, with owner, reason, start, and end time. Remove the pause by allowing the snooze to expire; avoid indefinite snoozes.
- **P2 at 36 hours while active:** notify the data owner through the Slack route, inspect upstream delay, and recover the missing source date. Do not publish an incomplete date.
- **P1 at 72 hours while active:** block new publish, escalate to the source owner and integrator, and verify last-good Gold remains unchanged.
- **Rerun/backfill:** rerun once the source is available and the idempotency key is preserved. Backfill only the required missing dates into an authorized isolated dataset after source recovery.
- **Quarantined candidate:** after the source is corrected and a fresh gate passes, follow [`quarantine-release.md`](quarantine-release.md) for the local harness. A live release requires separate authorization.
- **No failure in the owner check:** do nothing after capturing the check ID and source freshness result; do not add a G1 landing freshness test.

## Escalation and rollback

Escalate active P1 to the data owner and integrator. If the source is healthy and the alert is false, pause the affected schedule and review the threshold/input before changing policy. Keep alert flags off while intentionally stopped. A controlled rollout of `DQ_ENFORCE=warn` is not an incident workaround because it can publish P1 failures. No W7 schedule or resource change is authorized here.

For a controlled drill, record the injection time and delivered alert time to calculate MTTD. No active schedule or live notification evidence is claimed.
