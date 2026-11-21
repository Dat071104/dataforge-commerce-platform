# Postmortem-001: game day 001, duplicated landing row in `w9_drill`

**Status:** Final · **Date:** 2026-11-21 · **Format:** blameless · **Evidence level:** live alert path (Slack + Monitoring email) on the isolated `w9_drill` dataset; no production data involved.

## Setup
A separate Injector agent chose the fault at random from F01, F02, F03, F04, F06, F12 (seed `410672741`). It recorded its choice in a sealed file and returned only the injection time. A second Responder agent received only the alert lines, the runbooks and read access to `dataforge_dq`/`w9_drill`. It was forbidden to read the sealed file. The integrator unsealed the record only after the Responder had finished.

## Summary
The injected fault was **F02**: an exact duplicate of the HN row for 2026-10-30. The G1 gate blocked the date. Two P1 alerts reached Slack and email. The Responder diagnosed F02 correctly without seeing the sealed record, restored the date from the captured fixture, re-ran the gate green and resolved both alerts.

## Timeline (+07:00)
| Time | Event |
|---|---|
| 14:24:27 | Monitor watermark recorded by the Injector |
| 14:24:35 | **Injected:** `INSERT … SELECT … WHERE observation_date = DATE '2026-10-30' AND province_id = 'HN'` |
| ~14:25 | G1 gate exit 1: `G1.LANDING.GRAIN_UNIQUE` (2 failing rows) and `G1.LANDING.ROWS_PER_DATE` (1 date), both P1, `published=false` |
| 14:26:53 | Alerts sent: routes `SLACK_AND_MONITORING_EMAIL=2`, `delivery_failures=0` |
| 14:27:26 | Responder starts (acknowledge) |
| 14:28:39 | Fixture loaded into `w9_drill.gameday_restore_tmp` (21 rows) |
| 14:29:17 | Date 2026-10-30 replaced in one transaction (4 rows → 3 fixture rows); temp table dropped |
| 14:31:31 | Gate block mode exit 0, 9/9 checks PASS; monitor routes `RESOLVED=2`, `NO_ALERT=10`; 3 rows for the date, 21 in total |

## Metrics
- **MTTD** (injection → alert sent): **2 min 18 s**. Most of it is monitor latency from one Cloud Logging write per event (~5 s × 12 events); see action PM1-A1.
- **Time to acknowledge:** 33 s after the alert.
- **MTTR** (injection → verified green and resolved): **6 min 56 s**. The Responder's own repair took 4 min 05 s (14:27:26 → 14:31:31).
- **Diagnosis accuracy:** correct fault class (F02), correct row (HN duplicate, same `request_id`), correct date.
- `DRILL_EMAILS`: 3/6 for Week 9 (1 from H-W9-3 + 2 from this game day; one email per Monitoring policy).

## Root cause (of the simulated incident)
An exact duplicate of an already-landed record appeared in the landing table. In production, the likely real-world equivalent is a replayed load that bypassed the idempotency guard (F09 covers replays by `request_id` at ingest). The duplicate had the same `request_id`, so a landing-level idempotency check would have rejected it before the gate.

## What went well
- Defence in depth worked: the grain check and the volume check both fired, and publish stayed blocked.
- Slack and email arrived; nothing failed in delivery. The F-A1 fix (log before routing) was exercised in the live path.
- The `--since` watermark (R-20) kept earlier gate-test rows out of the incident.
- The Responder reached the right diagnosis from the alert's `failing_rows_query` plus one inspection query.

## What was hard (runbook gaps reported by the Responder)
1. No runbook described a restore of `w9_drill`, and `quarantine-release.md` covers only the local harness.
2. `VOLUME_ANOMALY` and F06 describe only missing provinces; here the date had too many rows.
3. One cause raised two P1 alerts under two runbooks, with no guidance on linking them.
4. The `ROWS_PER_DATE` observed value (`{"2026-10-30": 1}`) did not show the actual count.
5. No quarantine location or last-good hash exists for live `w9_drill`.
6. Runbook SQL uses `@params`, which does not paste into PowerShell `bq`.
7. No close-out step (gate in block mode, then `monitor --since --send-alerts`).
8. No guidance on downstream drill models.
9. No guidance on tracing the origin of a duplicate.

Gaps 1–3, 6 and 7 are addressed by the new [drill-restore-and-closeout.md](runbooks/drill-restore-and-closeout.md), linked from `VOLUME_ANOMALY.md` and `DQ_GATE_FAILED.md`. Gaps 5, 8 and 9 are recorded there as known limits, not fixed. Gap 4 is action PM1-A2. These PM1-A* IDs are separate from the RFC action items A1–A8.

## Action items
| # | Action | Owner | Status |
|---|---|---|---|
| PM1-A1 | Reuse one credential and batch `entries.write` in the monitor to cut MTTD by about 1 min | Q lane | Open |
| PM1-A2 | `ROWS_PER_DATE` observed value should include the actual and expected counts | Q lane | Open |
| PM1-A3 | Add a landing-level idempotency check on `request_id` before G1, so exact duplicates are rejected at ingest | Q lane | Open |
| PM1-A4 | Runbook close-out and restore guide | integrator | Done (this PR) |

## Evidence
[Responder timeline](evidence/gameday-001-responder-timeline.md) · [alert lines](evidence/gameday-001-alert.jsonl) · sealed record `DataForge_D_Week7_Final/evidence/w9/gameday_sealed.json` (operator machine; it contains synthetic weather rows only).
