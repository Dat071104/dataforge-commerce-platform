# Q8 Monitoring Terraform review plan

Status: Integrator applied separate fresh Q8 plans on 2026-11-19. Five log metrics and four policies now exist; three P1 policies are enabled, freshness is excluded, and the heartbeat/dead-man policy is disabled. Live event delivery and alert receipt remain **UNVERIFIED**.

## Proposed resources

`cloud/terraform/week9_dataops/metrics.tf` creates five log-based metrics when `enable_dq_alerting=true`: `DQ_GATE_FAILED`, `SCHEMA_DRIFT`, `FRESHNESS_BREACH`, `VOLUME_ANOMALY`, and `DQ_HEARTBEAT`. Filters are scoped to the `dataforge-week9-dq` log and `w9_drill` / `dbt_ci_pr_*` datasets, matching the DQ gate's isolation allowlist. Each metric extracts only `severity` and `status` labels.

`alerts.tf` creates P1 Monitoring email policies for gate failure, schema drift, freshness breach, and volume anomaly. Each requires `severity=P1` and `status=FAIL`, reuses the supplied existing C9 channel name, and links its corresponding runbook. P1 Slack remains in the runner. P2 events route to Slack; P3 events route to the digest collector. No extra notification channel is created, and Week 7 C3 resources are untouched. The freshness policy is additionally gated by `enable_dq_freshness_alert=false` by default so the intentionally stopped pipeline does not create a daily incident.

The fifth policy watches for the positive `DQ_HEARTBEAT` log metric to go absent for 23.5 hours (`84600s`, the documented maximum). It is present but disabled when DQ alerting is enabled; `enable_dq_deadman` defaults to `false`. Its aggregation uses a 60-second alignment period, making the total evaluation horizon 84,660 seconds (23 hours 31 minutes), below Monitoring's 25-hour limit. Enable only after a live schedule and maintenance-window procedure exist. Cloud Monitoring requires at least one data point after policy creation before absence detection can be evaluated ([metric-absence documentation](https://docs.cloud.google.com/monitoring/alerts/metric-absence)).

| Setting | Default | Review requirement |
|---|---:|---|
| `enable_dq_alerting` | `false` | Set true only after exact-head plan review |
| `c9_email_notification_channel_name` | `null` | Supply existing `projects/<project_id>/notificationChannels/<id>`; do not create a duplicate |
| `enable_dq_deadman` | `false` | Keep false while the pipeline is intentionally stopped |
| `enable_dq_freshness_alert` | `false` | Enable only after the freshness schedule is active |
| Metrics / policies | 0 / 0 | Alerting opt-in creates 5 metrics, 3 always-on P1 policies, and a disabled heartbeat policy; freshness adds the 4th P1 policy only when enabled |

## Verification and integrator actions

- The integrator verified the existing C9 channel through the read-only Monitoring API (`type=email`, enabled), then applied a fresh plan with that channel; no duplicate channel was created.
- Read-only Terraform state and Monitoring inventory confirmed five metrics and four policies. The first apply partially created the five metrics and three enabled P1 policies; Monitoring rejected the disabled dead-man policy because its 84,600-second alignment plus 84,600-second absence window exceeded 25 hours. A fresh one-resource plan set alignment to 60 seconds and applied the disabled policy; no resources were destroyed.
- Confirm the five structured event types and label values against a live isolated log entry. Confirm each linked Q9 runbook exists before enabling alerts.
- Review custom metric and Monitoring cost against the W9 cap, and leave the dead-man policy disabled until its operating schedule and maintenance window are approved.
- During a planned pipeline pause after activation, create a time-bounded [Cloud Monitoring snooze](https://docs.cloud.google.com/monitoring/alerts/snooze) with the maintenance reason and end time; do not leave an indefinite freshness or dead-man snooze. Keep `enable_dq_freshness_alert=false` and `enable_dq_deadman=false` while the pipeline is intentionally stopped. Keep `enable_dq_alerting=false` until the C9 channel and live event schema are reviewed.

Metric labels are extracted only from the structured event's `severity` and `status` fields, following [Cloud Logging's log-based metric label rules](https://docs.cloud.google.com/logging/docs/logs-based-metrics/labels).
