# H-W9-3 live alert drill: F06 on `w9_drill` (2026-11-21)

**Result: PASS.** A real P1 alert reached both Slack and email; the user confirmed receipt of both (H-W9-3). Only the isolated `w9_drill` dataset was changed; production datasets were not touched.

## Setup
- Fault F06 (2/3 provinces): delete province `DN` for observation date 2026-10-31 in `w9_drill.weather_landing` (21 rows, 7 dates × 3 provinces before the drill).
- Gate: `python -m dataforge.dq gate --layer landing --dataset w9_drill --date 2026-10-31` with `DQ_ENFORCE=block`, `DATAFORGE_DQ_RESULTS_ENABLED=true`.
- Alerting: `python -m dataforge.dq monitor --dataset w9_drill --date 2026-11-21 --since 2026-11-21T14:00:23+07:00 --send-alerts` (W9-Z head with R-16, R-20 watermark and F-A1 log-before-route). Email path: Cloud Logging `dataforge-week9-dq` → log metric `dataforge_w9_dq_volume_anomaly` → policy "DataForge W9 P1 volume anomaly" → C9 email channel. Slack path: webhook from Secret Manager (`w9-slack-webhook-url`).
- The day's F-N0 precision run (13:20) logged 12 PASS events and sent 0 alerts (operator log `evidence/w9/w9-3-4-fn0-precision-20261121.log`, copied as [w9-3-4-fn0-precision-20261121.log](w9-3-4-fn0-precision-20261121.log)).

## Timeline (+07:00)

| Time | Event | Source |
|---|---|---|
| 14:00:23 | Monitor watermark recorded | drill log |
| 14:00:40.061 | Backup of the DN row created (`w9_drill.f06_drill_backup_20261121`) | BigQuery job end time |
| **14:00:48.774** | **Fault injected** (DELETE committed) | BigQuery job end time |
| 14:01:15.209 | G1 gate exit 1, `blocked=true`, failed `G1.LANDING.ROWS_PER_DATE` (P1) → no publish | drill log |
| 14:01:46.502 | Structured `VOLUME_ANOMALY` FAIL event written to Cloud Logging | `entries.list` timestamp |
| ≤ 14:02:27.164 | Slack message sent; routes `SLACK_AND_MONITORING_EMAIL=1`, `NO_ALERT=11`, `delivery_failures=0` | monitor summary |
| after 14:01:46 | Monitoring incident email delivered (user confirmed; exact receive time not provided) | H-W9-3 user answer |
| 14:02:46.213 | DN row restored, date back to 3 rows, backup dropped | drill log |
| 14:04:37.806 | Gate re-run PASS (exit 0); monitor routed `RESOLVED=1` (Slack resolved message) | drill log |

## Measurements
- **Time to detect (gate):** 26.4 s. **Time to alert event:** 57.7 s. **MTTD Slack:** ≤ 98.4 s (sent before the monitor finished). **MTTD email:** delivered, not timed (the user did not record the receive time).
- **Time to restore data:** 1 min 58 s from injection. **MTTR (gate green and Slack RESOLVED):** 3 min 49 s.
- Cost: four 10-MiB minimum queries for backup/inject/restore/counts plus gate/monitor reads (≈ 0.1 GiB in total); see the cost ledger.
- `DRILL_EMAILS` 1/6 (AF7).

## Observations
- Monitor latency is dominated by one Cloud Logging write per event (~5 s each, credentials refreshed per write); 12 events took ~60 s before routing. Action item: reuse one credential and batch `entries.write`.
- A PowerShell formatting error lost the exact text of the resolve monitor line; the drill log records the route outcome.
