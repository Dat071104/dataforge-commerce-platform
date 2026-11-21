# W9 Game Day - Responder Timeline (w9_drill, 2026-10-30)

- Role: on-call Responder (did not cause the fault; no sealed material read)
- Response start (MTTR clock): **2026-11-21T14:27:26+07:00**
- Response end: **2026-11-21T14:32:00+07:00** (timeline written; verification complete at 14:31:31+07:00)
- MTTR (response start -> verified fix + RESOLVED sent): ~4 min 30 s (14:27:26 -> 14:31:14 monitor done; 14:31:31 final row-count check)
- Project confirmed before every write: `gcloud config get-value project` = `dataforge-p7-lab-d0f725`

## Alert received (gameday_alert.jsonl)

| event_type | check_id | severity/status | date | failing_rows | observed summary | threshold | published | run_id |
|---|---|---|---|---|---|---|---|---|
| DQ_GATE_FAILED | G1.LANDING.GRAIN_UNIQUE | P1 / FAIL | 2026-10-30 | 2 | `unexpected_count: 2` | unique on (request_id, province_id, observation_date) | false (BLOCK) | fc7443c7bc00479582c5866816e84f03 |
| VOLUME_ANOMALY | G1.LANDING.ROWS_PER_DATE | P1 / FAIL | 2026-10-30 | 1 | `{"2026-10-30": 1}` | rows_per_date = 3 | false (BLOCK) | fc7443c7bc00479582c5866816e84f03 |

Dataset is `w9_drill` (in scope per DQ_GATE_FAILED triage step 1 / VOLUME_ANOMALY triage step 2).

## Actions

| Local time | Action | Command summary | Result |
|---|---|---|---|
| 14:27:26+07:00 | Acknowledge, read alert + runbooks | read `gameday_alert.jsonl`; read `DQ_GATE_FAILED.md`, `VOLUME_ANOMALY.md`, `quarantine-release.md` | 2 P1 events, same run_id, same date |
| 14:27:33+07:00 | Triage: run failing_rows_query for both events | `bq query` on `dataforge_dq.dq_results` WHERE run_id='fc7443c7...' AND check_id IN (GRAIN_UNIQUE, ROWS_PER_DATE) | Both rows present, ts 2026-11-21 07:24:55 UTC, layer G1, contract 1.0.0, status FAIL, publish_action BLOCK, published false |
| 14:27:49+07:00 | Triage: per-date aggregate (VOLUME_ANOMALY triage step 3) + duplicate grain keys | `bq query` GROUP BY observation_date on `w9_drill.weather_landing`; GROUP BY request_id, province_id, observation_date HAVING n>1 | 2026-10-30 has **4 rows** (DN,HCM,HN,HN), all other 6 dates have 3. One grain key duplicated: province HN, 2026-10-30, request_id 29bb541d...bf86, n=2 |
| 14:28:14+07:00 | Triage: is the duplicate an exact copy? | `COUNT(DISTINCT TO_JSON_STRING(row))`, distinct landed_at, distinct source_sha256 per province for 2026-10-30 | HN: 2 rows, 1 distinct full row -> exact duplicate (same landed_at, same sha) |
| 14:28:27+07:00 | Load captured fixture to temp table | python: `bigquery_ready_parquet('tests/week9/faults/weather_7date_slice.parquet')` -> `load_table_from_file` (PARQUET, WRITE_TRUNCATE, us-central1) into `w9_drill.gameday_restore_tmp` | job 6f0ae414-04b3-4183-8302-9e2caddb4116 DONE, 21 rows, exit 0 (14:28:39) |
| 14:28:45+07:00 | Confirm no other defect vs source of truth | full-row JSON diff landing vs temp, both directions | 0 landing rows not in fixture, 0 fixture rows missing from landing, fixture total 21 -> only defect is the extra duplicate row |
| 14:29:06+07:00 | Fix: date-scoped restore (single transaction) | `BEGIN TRANSACTION; DELETE weather_landing WHERE observation_date='2026-10-30'; INSERT ... SELECT (explicit 11 columns) FROM gameday_restore_tmp WHERE observation_date='2026-10-30'; COMMIT` | DELETE 4 rows, INSERT 3 rows, exit 0 (14:29:17) |
| 14:29:23+07:00 | Drop temp table | `bq rm -f -t w9_drill.gameday_restore_tmp` | exit 0 |
| 14:29:28+07:00 | `$since` recorded | `$since = 2026-11-21T14:29:28+07:00` | |
| 14:29:28+07:00 | Verify: rerun gate, block mode | `$env:DQ_ENFORCE='block'; $env:DATAFORGE_DQ_RESULTS_ENABLED='true'; python -m dataforge.dq gate --layer landing --dataset w9_drill --date 2026-10-30` | **exit 0, `"blocked": false`**, run_id 862c112f30734cf98b3b534806b8619f, all 9 G1 checks PASS (GRAIN_UNIQUE unexpected_count 0; ROWS_PER_DATE `{"2026-10-30": 0}`) (14:29:47) |
| 14:29:47+07:00 | Verify: monitor + resolve Slack alert | `python -m dataforge.dq monitor --dataset w9_drill --date 2026-11-21 --since $since --send-alerts` | **exit 0**: `{"events": 12, "routes": {"NO_ALERT": 10, "RESOLVED": 2}, "delivery_failures": 0, "daily_digest_events": 0, "logged_to_cloud": true}` (14:31:14) |
| 14:31:19+07:00 | Verify: final row counts + temp table gone | per-date GROUP BY on weather_landing; `bq ls w9_drill` | 7 dates x 3 rows (DN,HCM,HN each), **total 21**; `gameday_restore_tmp` absent |
| 14:31:43+07:00 | Map to fault catalog | grep `docs/week9/failure_modes.md` | matches **F02 Uniqueness** (duplicate grain key; G1.LANDING.GRAIN_UNIQUE primary, P1, block) |

## Diagnosis

Fault class F02 (uniqueness): `w9_drill.weather_landing` contained an **exact duplicate of the HN row for observation_date 2026-10-30** (same request_id, all columns identical incl. landed_at and source_sha256). This one extra row caused both alerts:
- `G1.LANDING.GRAIN_UNIQUE`: 2 rows share the key (HN, 2026-10-30, request_id 29bb541d...) -> failing_rows 2.
- `G1.LANDING.ROWS_PER_DATE`: 2026-10-30 had 4 rows instead of 3 -> 1 date failing (over-count, not a missing province).
No values were altered: every landing row matched a fixture row, and the other 6 dates were already correct. Publish was blocked (`published=false`), so nothing downstream was released by the gate.

## Runbook step followed

- `DQ_GATE_FAILED.md` -> Triage 1-4 (scope check, record fields, dq_results summary query, map check_id to failure_modes.md -> F02), then Decision: **"P1 / FAIL / publish blocked: preserve the quarantined batch ... Fix the owning source or check, then rerun the bounded validation."**
- `VOLUME_ANOMALY.md` -> Triage step 3 (aggregate keys per date) and Decision **"block the whole date ... Correct the upstream source or the ingestion gap, then run a bounded retry."** and "Never publish a partial daily population to clear the alert."
- Chosen action: **rerun/restore of the single affected date from the source of truth** (captured fixture) - not a quarantine release (`quarantine-release.md` is local-WAP only), not a contract fix (contract is correct; the data is wrong), not do-nothing (P1 FAIL). Gate not weakened, `DQ_ENFORCE=warn` not used.

## Fix

Loaded fixture -> `w9_drill.gameday_restore_tmp`; in one transaction deleted the 4 rows of 2026-10-30 and inserted the 3 fixture rows for that date; dropped the temp table. Other dates untouched.

## Verification

- Gate (block): exit 0, `"blocked": false`, 9/9 G1 checks PASS, run_id 862c112f30734cf98b3b534806b8619f.
- Monitor (`--since 2026-11-21T14:29:28+07:00 --send-alerts`): exit 0, routes `NO_ALERT: 10, RESOLVED: 2`, delivery_failures 0.
- Table: 2026-10-30 = 3 rows (DN, HCM, HN); 7 dates x 3 = 21 rows total. Temp table dropped.

## Runbook gaps I hit

1. **No live restore procedure.** Both runbooks say "No production write is authorized" and `quarantine-release.md` explicitly covers only the local WAP harness ("does not authorize cloud writes"). The actual fix (fixture -> temp table -> delete/insert one date) came from the game-day brief, not any runbook. A `w9_drill` live date-restore section is missing.
2. **Duplicate rows are not covered by VOLUME_ANOMALY.** That runbook (and fault catalog F06) only describes ROWS_PER_DATE as "incomplete / two of three provinces". Here the same check fired for an **over-count** (4 rows). The runbook should say an over-count usually co-occurs with GRAIN_UNIQUE and to triage under F02.
3. **One root cause, two P1 events, two runbooks.** No guidance on correlating events with the same run_id/date or which runbook is primary; the on-call has to work that out.
4. **Ambiguous ROWS_PER_DATE observed value.** `{"2026-10-30": 1}` / `failing_rows: 1` does not say the actual row count (4) or the direction (over vs under); I needed a table query to find out.
5. **"Preserve the quarantined batch and confirm the last-good hash" can't be done live.** There is no quarantine location or Gold hash/manifest for `w9_drill` in BigQuery, so this Decision step could not be executed or evidenced.
6. **Triage query mismatch.** The alert's `failing_rows_query` differs from the runbook SQL (no `ts`/`layer`/`contract_version`, no dataset filter); the runbook SQL uses `@params` with no note on how to run it from PowerShell/bq (quoting).
7. **No verification/close-out step.** Neither runbook says to rerun the gate with `DQ_ENFORCE=block` for the date and then run `dq monitor --since ... --send-alerts` to send the RESOLVED notification; neither defines "resolved".
8. **Downstream not addressed.** `w9_drill.int_weather_daily` is a materialized TABLE; the runbook does not say whether to check/rebuild downstream models after a landing repair (not touched here because it was outside my write scope; publish was blocked so it should not have consumed the bad batch - owner to confirm).
9. **Root cause upstream not identified.** The runbook says "fix the owning source", but gives no way to find out how the duplicate got in (load job history/ingestion idempotency key), so the fix only repairs the symptom. Escalation to the ingestion owner is recommended.
