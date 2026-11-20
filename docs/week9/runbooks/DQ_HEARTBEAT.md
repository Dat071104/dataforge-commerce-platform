# DQ_HEARTBEAT

## Symptom and impact

`ALERTING.DQ_HEARTBEAT` is an informational P3 event emitted only when a successful G2 weather check exists. It proves that the monitor saw a successful check and logged a heartbeat; it is not an ingestion or data-quality failure. The Monitoring policy detects 23.5 hours without a heartbeat and is disabled by default (`enable_dq_deadman=false`). Cloud Monitoring requires a data point after the policy is created before it can evaluate absence.

The W7 Airflow VM and schedule are intentionally stopped. While no active schedule exists, a missing heartbeat is expected: keep the policy disabled. P3 events belong in the digest, not email or immediate Slack.

## Triage

1. Check the current operating state and maintenance log. If the pipeline is intentionally stopped, record “expected absence” and take no action.
2. For an active isolated schedule, inspect the latest successful G2 weather checks:

```sql
SELECT ts, run_id, check_id, layer, severity, status,
       JSON_VALUE(observed, '$.dataset') AS dataset,
       JSON_VALUE(observed, '$.date') AS event_date
FROM `dataforge-p7-lab-d0f725.dataforge_dq.dq_results`
WHERE layer = 'G2'
  AND check_id LIKE 'G2.WEATHER.%'
  AND status = 'PASS'
  AND JSON_VALUE(observed, '$.dataset') = @dataset
ORDER BY ts DESC
LIMIT 10;
```

3. Verify the monitor job ran with the authorized `--emit-logs` path and that its `DQ_HEARTBEAT` structured entry reached the `dataforge-week9-dq` log. The monitor CLI is opt-in; it does not schedule itself.
4. Check alert policy state and snoozes. A snooze must identify the policy, owner, reason, start, and end time.

## Decision

- **Pipeline stopped or inside a planned window:** do nothing; leave `enable_dq_deadman=false`. If the policy is already active during a planned pause, use a time-bounded [Cloud Monitoring snooze](https://docs.cloud.google.com/monitoring/alerts/snooze) and document its expiration.
- **Schedule active, latest G2 pass exists, but no heartbeat event:** rerun the read-only monitor in the approved isolated environment and inspect the structured log. Do not query or copy raw landing rows.
- **Schedule active and no recent G2 pass:** inspect the corresponding DQ gate and failure runbook. Retry only after the cause is corrected; backfill only missing dates through an authorized isolated path.
- **Policy is noisy or schedule is paused:** keep/return the policy to disabled through the reviewed change and record the maintenance reason. Do not delete the metric or alter W7 resources to quiet it.
- **Quarantine release:** not part of heartbeat recovery. If a separate P1 gate quarantined data, follow [`quarantine-release.md`](quarantine-release.md) after its own gate passes.

## Escalation and rollback

Enable the dead-man policy only after a live schedule, first heartbeat sample, owner, and maintenance-window process are in place. Escalate an unexplained active-schedule gap to the data owner and integrator. Roll back by disabling the W9 policy through a reviewed config change or allowing the documented snooze to expire; no W7 resource change or cloud write is authorized by this runbook.

If a controlled heartbeat drill is authorized, record the expected heartbeat time, missing interval, incident-open time, and notification-received time. MTTD and delivery are currently **UNVERIFIED**.
