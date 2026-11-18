# Q8 Monitoring Terraform review plan

Status: HCL is authored for integrator review. Terraform plan, apply, and live alert evidence are **UNVERIFIED**; no Terraform plan/apply or GCP API command was run because the integrator's cloud authorization is expired.

## Proposed resources

`cloud/terraform/week9_dataops/metrics.tf` creates five log-based metrics when `enable_dq_alerting=true`: `DQ_GATE_FAILED`, `SCHEMA_DRIFT`, `FRESHNESS_BREACH`, `VOLUME_ANOMALY`, and `DQ_HEARTBEAT`. Filters are scoped to the `dataforge-week9-dq` log and `w9_drill` / `dbt_ci_pr_*` datasets, matching the DQ gate's isolation allowlist. Each metric extracts only `severity` and `status` labels.

`alerts.tf` creates P1 Monitoring email policies for gate failure, schema drift, freshness breach, and volume anomaly. Each requires `severity=P1` and `status=FAIL`, reuses the supplied existing C9 channel name, and links its corresponding runbook. P1 Slack remains in the runner. P2 events route to Slack; P3 events route to the digest collector. No extra notification channel is created, and Week 7 C3 resources are untouched. The freshness policy is additionally gated by `enable_dq_freshness_alert=false` by default so the intentionally stopped pipeline does not create a daily incident.

The fifth policy watches for the positive `DQ_HEARTBEAT` log metric to go absent for 23.5 hours (`84600s`, the documented maximum). It is present but disabled when DQ alerting is enabled; `enable_dq_deadman` defaults to `false`. Enable only after a live schedule and maintenance-window procedure exist. Cloud Monitoring requires at least one data point after policy creation before absence detection can be evaluated ([metric-absence documentation](https://docs.cloud.google.com/monitoring/alerts/metric-absence)).

| Setting | Default | Review requirement |
|---|---:|---|
| `enable_dq_alerting` | `false` | Set true only after exact-head plan review |
| `c9_email_notification_channel_name` | `null` | Supply existing `projects/<project_id>/notificationChannels/<id>`; do not create a duplicate |
| `enable_dq_deadman` | `false` | Keep false while the pipeline is intentionally stopped |
| `enable_dq_freshness_alert` | `false` | Enable only after the freshness schedule is active |
| Metrics / policies | 0 / 0 | Alerting opt-in creates 5 metrics, 3 always-on P1 policies, and a disabled heartbeat policy; freshness adds the 4th P1 policy only when enabled |

## Verification and integrator actions

- Local HCL formatting/static validation is recorded in the Q lane report. No cloud-backed plan was generated.
- When authorization is restored, obtain the C9 channel resource name from the existing W7 operations state and pass it as a protected plan variable. Review a plan from this branch's exact commit before any apply.
- Confirm the five structured event types and label values against a live isolated log entry. Confirm each linked Q9 runbook exists before enabling alerts.
- Review custom metric and Monitoring cost against the W9 cap, and leave the dead-man policy disabled until its operating schedule and maintenance window are approved.
- During a planned pipeline pause after activation, create a time-bounded [Cloud Monitoring snooze](https://docs.cloud.google.com/monitoring/alerts/snooze) with the maintenance reason and end time; do not leave an indefinite freshness or dead-man snooze. Keep `enable_dq_freshness_alert=false` and `enable_dq_deadman=false` while the pipeline is intentionally stopped. Keep `enable_dq_alerting=false` until the C9 channel and live event schema are reviewed.

Metric labels are extracted only from the structured event's `severity` and `status` fields, following [Cloud Logging's log-based metric label rules](https://docs.cloud.google.com/logging/docs/logs-based-metrics/labels).
