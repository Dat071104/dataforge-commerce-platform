# W9 fault matrix evidence (Mini-project 4)

Evidence levels: **CI-fixture** = deterministic fixture run in GitHub Actions on an exact head; **CI-live** = isolated BigQuery job in GitHub Actions (`w9_drill` / `dbt_ci_pr_<n>`); **local** = run on the operator laptop; **live-alert** = a real alert delivered by email/Slack.

## F01–F12, F-T1, F-N0 (CI-fixture)

Source: `fault-matrix-<fault>` artifacts of run `44867546904` (`pull_request_target`) on #52 exact head `0f6c5fb`, which was merged as `9e78c22`. Each fixture runs the real G0/G1 gate code against a captured landing slice and a local WAP copy; no alert is sent.

| Fault | Injected defect | Detector (`check_id`) | Expected action | Observed action | Gold hash before = after | Result |
|---|---|---|---|---|---|---|
| F01 | `province_id` NULL | `G1.LANDING.PROVINCE_ID_NOT_NULL` | P1 block | BLOCK | yes | PASS |
| F02 | duplicate grain | `G1.LANDING.GRAIN_UNIQUE` | P1 block | BLOCK | yes | PASS |
| F03 | `temp_max_c=99`, `precipitation_mm=-5` | `G1.LANDING.PHYSICAL_RANGE` | P1 block | BLOCK | yes | PASS |
| F04 | province `SG` | `G1.LANDING.PROVINCE_DOMAIN` | P1 block | BLOCK | yes | PASS |
| F05a | renamed / retyped column | `G0.API.SCHEMA` + `G1.LANDING.SCHEMA` | P1 block | BLOCK | yes | PASS |
| F05b | additive nullable column | `G1.LANDING.SCHEMA_ADDITIVE` | P2 publish + warn | WARN_PUBLISH | no (published by design) | PASS |
| F06 | 2/3 provinces | `G1.LANDING.ROWS_PER_DATE` | P1 block | BLOCK | yes | PASS |
| F08 | future `observation_date` | `G1.LANDING.NO_FUTURE_DATE` | P1 block | BLOCK | yes | PASS |
| F09 | replayed `request_id` | `G1.LANDING.IDEMPOTENCY_REPLAY` | NO_OP, 0 alerts | NO_OP | yes | PASS |
| F11 | HTTP 200 with missing days | `G0.API.RESPONSE_COMPLETENESS` | block before landing | BLOCK_BEFORE_LANDING | yes | PASS |
| F12 | °F values (80–100) | `G1.LANDING.TEMP_UNIT_RANGE` | P1 block | BLOCK | yes | PASS |
| F-T1 | one HTTP 503 | `G0.API.TRANSIENT_RETRY` | retry, 0 P1 | RETRY_THEN_SUCCEED | yes | PASS |
| F-N0 | clean data | `ALERTING.NEGATIVE_CONTROL` | 0 alerts | NO_OP | yes | PASS |

F09 and F-T1 are the harness-level replacements for the Week 7 S4 NO_OP and S6 retry drills that were never run live; they are not live evidence.

## F07, F10 (CI-live, isolated BigQuery)

| Fault | Detector | Run | Result |
|---|---|---|---|
| F07 stale landing (> 72 h) | `G2.SOURCE.FRESHNESS` (dbt source freshness) | PENDING | PENDING |
| F10 `rain_day=TRUE` with zero precipitation | `G2.WEATHER.RAIN_PRECIP_CONSISTENCY` (dbt singular test, P1) | PENDING | PENDING |

First live attempts on #56 (`44871686099`) and #57 (`44871827026`) returned `UNVERIFIED (RuntimeError)`. RCA R-18: the captured parquet stores `landed_at` as `timestamp[ns, UTC]`; BigQuery has no nanosecond TIMESTAMP, so the load made it INT64 and `stg_weather_mini3_landing` failed with "Invalid cast from INT64 to TIMESTAMP" (BigQuery job history, 05:45:33Z). Fixed in `fed8ea9`.

## F13–F15 (throwaway PR fixtures)

| Fault | PR | Expected detector | Observed | Result |
|---|---|---|---|---|
| F13 raw e-mail column in public Gold mart | #54 (closed) | PII-leak guard | CI red: "DataOps toolbox build and offline gates" job `136748255564` failed in the governance unit test (Gold column registry count 56 ≠ 55), which runs before the guard step. Local run of `scripts/week9_pii_guard.py` on the PR manifest: `PII_GUARD_STATUS=FAIL`, one finding `reporter_email` (public, email), exit 1. | PASS (blocked); guard proven locally, CI caught it one step earlier |
| F14 drop contracted Gold column `temp_max_c` | #55 (closed) | `datacontract breaking` vs `origin/main` | CI red: job `136744399247`, step "Check contract compatibility against main", `Removed` property `temp_max_c` | PASS |
| F15 `temp_max_c + 1` in the Gold mart | #56 | slim-CI build + data diff vs production | PENDING. First run `44871686099` failed before the diff: R-17 (state manifest parsed with a fake offline target, so `--defer` could not reach production). Fixed in `f2a11f2`. | PENDING |

## Live alert drill (H-W9-3)

See `h-w9-3-f06-live-drill.md` (2026-11-21 14:00–14:15 +07).
