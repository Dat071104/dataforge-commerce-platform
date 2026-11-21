# DQ_GATE_FAILED

## Symptom and impact

A structured `DQ_GATE_FAILED` event reports a recorded G0/G1/G2 check failure that does not have a more specific monitor event type. Use `check_id` and the fault catalog to identify the owner. P1/FAIL should block publish and preserve the last-good Gold hash. A P1 result with `published=true` is a release-mode or integration exception: stop downstream use and escalate immediately. P2/WARN may publish.

`ALERTING.DQ_GATE_ADAPTER_UNAVAILABLE` is a control-plane sentinel, not a fault-catalog data check. It means `DATAFORGE_DQ_GATE_ENABLED=true` reached the W7 Airflow reference DAG without an isolated W9 adapter. The intended behavior is fail-closed before dbt; keep the flag false in W7 until an authorized adapter is integrated.

P1 notifications route to Slack and the existing C9 Monitoring email channel when the opt-in routes are enabled. P2 routes to Slack. A clean F-N0 control must produce zero P1/P2 alerts.

## Triage

1. Confirm `dataset` is `w9_drill` or an approved `dbt_ci_pr_*`. Stop if the event refers to any other dataset.
2. Record the event's `run_id`, `check_id`, `date`, `severity`, `status`, `failing_rows`, `published`, and `runbook_url`. Do not copy row values or secret material into tickets or logs.
3. For persisted gate results, retrieve only the summary fields:

```sql
SELECT ts, run_id, check_id, layer, severity, status, failing_rows, contract_version
FROM `dataforge-p7-lab-d0f725.dataforge_dq.dq_results`
WHERE run_id = @run_id
  AND check_id = @check_id
  AND JSON_VALUE(observed, '$.dataset') = @dataset
ORDER BY ts DESC
LIMIT 20;
```

4. Map `check_id` to `docs/week9/failure_modes.md`. If row-level diagnosis is required, query only the isolated synthetic dataset and return counts or approved keys; never write row values to the alert or log.

## Decision

- **P1 / FAIL / publish blocked:** preserve the quarantined batch and confirm the before/after last-good hash matches. Fix the owning source or check, then rerun the bounded validation. Use [`quarantine-release.md`](quarantine-release.md) only for its local WAP harness. A live release requires separate implementation and authorization.
- **P1 / FAIL / published:** pause downstream consumption and escalate to the data owner and integrator. Do not use `DQ_ENFORCE=warn` as an incident workaround; that mode can publish a P1 failure.
- **P2 / WARN:** publish is allowed. Determine whether the warning is an approved additive or known variation. Fix the source/contract if it is unexpected; otherwise document the decision and take no further action.
- **Transient F-T1 recovered:** verify the bounded retry succeeded. Do not send a P1 alert or repeat requests indefinitely.
- **Missing expected date:** backfill only through the reviewed isolated path after the source is corrected; preserve the idempotency key and verify no duplicate publish.
- **Clean PASS / F-N0:** do nothing; the negative control must remain at zero alerts.

## Escalation and rollback

Escalate unresolved P1 failures to the data owner and W9 integrator the same day; send P2 items to the owner within one business day. If PII or an out-of-scope dataset appears, stop the drill and involve the governance owner. If a false positive is traced to a code change, pause the affected schedule and revert that change after review. For local WAP, restore the saved `published/weather_landing.parquet` with the manifest's last-good SHA-256. No production rollback or write is authorized by this runbook.

For any controlled alert drill, record injection time and delivered alert time separately to calculate MTTD. No live MTTD or notification delivery is claimed here.

## Drill restore and close-out

For the isolated `w9_drill` dataset, follow [drill-restore-and-closeout.md](drill-restore-and-closeout.md): it covers several alerts from one cause, missing vs. extra rows, restoring one date, and the required close-out (gate in block mode, then `monitor --since --send-alerts` to resolve).
