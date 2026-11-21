# Drill restore and incident close-out (isolated `w9_drill` only)

Added after game day 001 ([postmortem-001](../postmortem-001.md)); it fills gaps the responder hit. It applies only to the isolated drill dataset. Production has no write path in W9.

## 1. One cause, several alerts
A single bad batch can raise several P1 events at once. In game day 001, one duplicated row raised `G1.LANDING.GRAIN_UNIQUE` (DQ_GATE_FAILED) and `G1.LANDING.ROWS_PER_DATE` (VOLUME_ANOMALY). Group the alerts by `run_id` and `date`. Open one incident, follow the runbook of the most specific check (grain/null/domain before volume), and close every alert from that run together.

## 2. Read the row-count evidence correctly
`ROWS_PER_DATE` fails when the count is **not** 3, which can mean missing rows or extra rows. Run this before deciding:
```sql
SELECT province_id, COUNT(*) AS n, COUNT(DISTINCT request_id) AS requests
FROM `dataforge-p7-lab-d0f725.w9_drill.weather_landing`
WHERE observation_date = DATE '<date>'
GROUP BY province_id ORDER BY province_id;
```
In PowerShell, keep the SQL in single quotes and use only single-quoted literals. The `@params` queries in other runbooks are for the BigQuery console.

## 3. Restore one date from the captured fixture
The drill table is loaded from `tests/week9/faults/weather_7date_slice.parquet` (7 dates × 3 provinces).
1. Load the fixture into `w9_drill.gameday_restore_tmp`: `bigquery_ready_parquet()` from `deploy/dataops_toolbox/week9_live_faults.py`, then `WRITE_TRUNCATE`.
2. In one transaction, delete the affected date from `weather_landing` and insert that date's rows from the temp table. Do not touch other dates.
3. Drop the temp table.
Never use `DQ_ENFORCE=warn` and never weaken a check to get a green run.

## 4. Close-out (required)
1. `$since = (Get-Date).ToString('yyyy-MM-ddTHH:mm:sszzz')`
2. Re-run the gate in block mode for the date and require `"blocked": false`.
3. `python -m dataforge.dq monitor --dataset w9_drill --date <today> --since $since --send-alerts`. Expect one `RESOLVED` route per alert that was open.
4. Confirm 3 rows for the date and 21 rows in the table.
5. Record start, fix, verified and end times in the incident timeline.

## 5. Known limits
- `w9_drill` has no quarantine location or last-good hash. Hash checks exist only in the local WAP harness (`quarantine-release.md`).
- Downstream drill models (`int_weather_daily` and later) are rebuilt by the next CI/live-fault run, not by the responder.
- Finding where a duplicate came from (request replay vs. ingest bug) belongs to the ingestion owner. Escalate it with the `request_id`.
