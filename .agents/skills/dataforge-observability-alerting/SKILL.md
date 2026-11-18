---
name: dataforge-observability-alerting
description: Build or review DataForge freshness, volume, schema-drift and distribution monitors, structured DQ events, log-based metrics, alert routing to Slack and email, runbooks and MTTD measurement.
---

# Observability and alerting (Week 9)

1. Monitors read from `dataforge_dq.dq_results` and `INFORMATION_SCHEMA`. They do not re-implement gate logic.
2. Freshness = `max(landed_at)` plus dbt source freshness. Volume = exact expected rows per date when known. Schema drift = `INFORMATION_SCHEMA.COLUMNS` compared with the contract (added / dropped / type changed). Distribution checks are P2 warnings only.
3. Emit one structured JSON log line per finding: `event_type` (DQ_GATE_FAILED | SCHEMA_DRIFT | FRESHNESS_BREACH | VOLUME_ANOMALY | DQ_HEARTBEAT), `run_id`, `check_id`, `severity`, `dataset`, `date`, `runbook_url`. No PII, no secrets, no row values beyond keys.
4. Log-based metrics and alert policies are Terraform in `cloud/terraform/week9_dataops/` (`metrics.tf`, `alerts.tf`). Reuse the existing C9 email channel. Every policy has a runbook link in its documentation field. Never edit the W7 C3 policies.
5. Slack: read the webhook URL from Secret Manager `w9-slack-webhook-url` at runtime. Never log or print it. A message states what failed, the impact (published or not), run_id, a failing-rows query and the runbook link. Deduplicate by (check_id, date) and send a resolve message when the check passes again.
6. Routing: P1 goes to Slack + email; P2 to Slack; P3 to a daily digest only.
7. Each alert type has `docs/week9/runbooks/<event_type>.md`: symptom, triage queries, decision tree (rerun / backfill / release quarantine / fix contract / do nothing), escalation and rollback.
8. Precision: the clean run (F-N0) must produce 0 alerts. MTTD = alert received time minus injection time, backed by a screenshot or API record that shows the time.
9. Alert fatigue: when the pipeline is stopped on purpose (after the W7 VM teardown), snooze freshness and dead-man's-switch policies with a documented maintenance window. Do not let them fire every day.
