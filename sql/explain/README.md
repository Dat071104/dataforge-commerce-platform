# q10 EXPLAIN before and after

`tests/learning/test_q10_explain_plan.py` creates an isolated PostgreSQL database with a fixed synthetic `dw.fct_order_item` fixture, then runs the existing `sql/analysis/q10_explain_performance.sql` query with `EXPLAIN (ANALYZE, BUFFERS)`. It captures one plan with the baseline `order_date_key` index and another after the candidate covering index in `sql/performance/002_q10_covering_index.sql`. The test records the plan text and validates that both plans are present; it does not assert a speedup or require a particular access path because the planner depends on statistics and PostgreSQL version.

The test skips unless `RUN_POSTGRES_TESTS=1`, matching the repository's opt-in PostgreSQL integration suite. In GitHub Actions, the existing disposable PostgreSQL 16 service provides the test target. The plan text is also appended to `GITHUB_STEP_SUMMARY` when that Actions environment variable is available.
