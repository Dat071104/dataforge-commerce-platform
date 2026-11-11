# P7.3 / Week 6 — independent controller verdict

**Decision: `GO_WEEK6_LOCAL`**
**Release ready:** Yes, for feature-branch commit, push, and PR. Merge requires hosted CI on the exact PR head with no blocking findings.
**Managed Spark:** not run; not required for this local verdict.

The single independent final controller inspected the actual working tree, code, tests, local run receipts, event logs, physical plans, Parquet/Delta outputs, and accepted baseline diff. It did not mutate cloud resources or rerun the expensive Spark job.

## Acceptance evidence

| Gate | Controller result |
|---|---|
| Git/base preservation | `HEAD` and `origin/main` were `839f7a5a2e39f3fec6c071d8a8a04a1c07ea70a4`; live GitHub API `main` matched. Shell `git fetch` was unable to connect; remote state was verified through the GitHub connector. No diff to commerce source, SQL, tests, Terraform, or cloud job code. |
| Official source and scale | Verified hashes/bytes for four official 2024 Yellow Taxi files and the zone lookup. Spark materialized **13,069,067** rows and matched the footer total; all four Parquet schemas matched at 19 columns. |
| Quality and correctness | **12,686,794 accepted + 382,273 rejected = 13,069,067**. Full DataFrame/SQL parity had zero different rows. The full January 15 date partition matched the independent PyArrow/Python Decimal oracle: 77,033 source rows, 74,680 accepted, 2,353 rejected; exact counts and decimal sums matched. |
| Benchmark and plans | Recalculated five timed runs per variant from 12 successful event-log groups. Median: **213.924 s baseline**, **256.307 s broadcast**. Broadcast reduced shuffle write by 65.6% and spill, but was 19.8% slower. Executed plans showed baseline `SortMergeJoin` and candidate `BroadcastHashJoin`; no speedup was claimed. |
| Parquet and Delta | Output manifest was `COMPLETE`; all **121** recorded Parquet file hashes independently verified. The 308,833 rows span 121 date partitions and sum to accepted trips. Same-run replay was a verified no-op. Real Delta append/replay/history/version-0 readback passed. |
| Tests and safety | Local Spark CI: **30 passed**. Commerce regression: **155 passed / 7 expected skips** offline and **161 passed / 1 expected skip** with PostgreSQL, using temporary databases. Ruff, compileall, pip check, Power BI source-pack validation, and `git diff --check` passed. No cloud mutation or Week 7 work. |

## Findings and limitations

**Material findings:** none.

The benchmark is local and variable. Its timing receipt was recovered from the completed Spark event log after the original wrapper stopped on a strict summary-equality assertion; a final key-aligned check then passed exact counts/money/distance and the declared percentile tolerance. The Spark UI REST API worked inside the container, but the Windows host port timed out and the computer-use helper could not determine Chrome’s current URL, so no screenshot is claimed. Manual capture steps and event-log metrics are documented. A managed Spark batch was not authorized, and no settled-billing claim is made.

**Minor hardening note:** the lab build context has no `.dockerignore`. The Dockerfile does not copy source data into the image and raw TLC files are git-ignored; an explicit Docker ignore file would protect against future broad `COPY` instructions. This does not block release.
