# Week 9 failure modes

Status: planned catalog, based on `11_WEEK9_PLAN.md` §§4.2 and 5. The check IDs below are stable identifiers for implementation; they are not evidence that a gate is already implemented. Each check has one owning layer. Where two layers appear, they guard different boundaries or are the explicitly planned second-line defense.

| ID | Type | Injected fault | Layer / location | Expected detector check_id | Severity | Expected action |
|---|---|---|---|---|---|---|
| F01 | Validity | `province_id` is NULL | Landing | `G1.LANDING.PROVINCE_ID_NOT_NULL` | P1 | Block; quarantine; Gold hash unchanged |
| F02 | Uniqueness | Duplicate `(request_id, province_id, observation_date)` within one request | Landing / silver | `G1.LANDING.GRAIN_UNIQUE` (primary); `G2.WEATHER.GRAIN_UNIQUE` (defense in depth) | P1 | Block; quarantine; Gold hash unchanged |
| F03 | Range | `temp_max_c = 99` and `precipitation_mm = -5` | Landing | `G1.LANDING.PHYSICAL_RANGE` | P1 | Block; quarantine; Gold hash unchanged |
| F04 | Domain | `province_id = SG` | Landing | `G1.LANDING.PROVINCE_DOMAIN` | P1 | Block; quarantine; Gold hash unchanged |
| F05a | Breaking schema drift | Required field renamed/removed or its type changed | API payload / landing | `G0.API.SCHEMA` and `G1.LANDING.SCHEMA` | P1 | Block before publish; quarantine; Gold hash unchanged |
| F05b | Additive schema drift | A new nullable field appears | Landing | `G1.LANDING.SCHEMA_ADDITIVE` | P2 | Publish; warn; record schema change |
| F06 | Volume | Only two of the three provinces arrive for a date | Landing | `G1.LANDING.ROWS_PER_DATE` | P1 | Block the whole date; quarantine; Gold hash unchanged |
| F07 | Freshness | No new landing for more than 36 hours / 72 hours | Source / monitor | `G2.SOURCE.FRESHNESS` | P2 / P1 | Warn after 36h; alert and block a new publish after 72h |
| F08 | Timeliness | `observation_date` is in the future | Landing | `G1.LANDING.NO_FUTURE_DATE` | P1 | Block; quarantine; Gold hash unchanged |
| F09 | Idempotency | Replay the same `request_id` | Landing | `G1.LANDING.IDEMPOTENCY_REPLAY` | None | NO_OP; no new output; zero alert |
| F10 | Consistency | `rain_day = TRUE` while precipitation is zero | Gold model | `G2.WEATHER.RAIN_PRECIP_CONSISTENCY` | P1 | Block; quarantine; Gold hash unchanged |
| F11 | Silent upstream failure | HTTP 200 with an empty daily array or a requested date missing | Ingest response | `G0.API.RESPONSE_COMPLETENESS` | P1 | Block before landing; quarantine manifest with reason |
| F12 | Semantic drift | Fahrenheit-like values (80–100) are interpreted as Celsius | Landing | `G1.LANDING.TEMP_UNIT_RANGE` | P1 | Block; quarantine; Gold hash unchanged |
| F13 | Privacy code fault | A raw PII column flows into a public mart | PR | `CI.PII.PUBLIC_MART_GUARD` | P1 | Fail the PR |
| F14 | Contract code fault | A contracted Gold column is removed or its type changes | PR | `CI.CONTRACT_BREAKING` | P1 | Fail the PR |
| F15 | Historical regression | Logic change shifts historical values | PR | `CI.DATA_DIFF_REVIEW` | P2 | Require review; do not silently approve the diff |
| F-T1 | Transient | One HTTP 503, followed by a successful retry | Ingest response | `G0.API.TRANSIENT_RETRY` | None | Succeed after retry; zero P1 alert |
| F-N0 | Negative control | Clean data | Full gate path | `ALERTING.NEGATIVE_CONTROL` | None | Zero P1/P2 results and zero alerts |

## Severity and publish policy

| Severity | Gate result | Publish behavior | Routing |
|---|---|---|---|
| P1 | Blocking failure | Do not publish; quarantine the batch; assert the published Gold hash is unchanged | Slack + email; response within the day |
| P2 | Warning | Publish; record the warning | Slack; response within one business day |
| P3 | Informational | Record only and include in the digest | Weekly digest |

One check ID names the contract rule and the owning implementation. `G0.API.SCHEMA` validates the upstream payload before it is landed; `G1.LANDING.SCHEMA` validates the physical landing boundary. F02's dbt assertion is a separate defense over the transformed weather grain. All drill data must be copied into `w9_drill` or `dbt_ci_pr_<n>`; no fault run writes to `weather_mini3`, `dbt_weather_mini3`, `silver`, `gold`, `ops`, or Week 5/7 resources.

Baseline: no fault fixture is currently mapped to this catalog (`docs/week9/baseline.md`). Each P1 detector must gain a failing fixture; F-N0 must remain a clean zero-alert control. Evidence is reported per fault as unit, CI (Linux runner), or live GCP (isolated dataset); this catalog alone is not implementation evidence.
