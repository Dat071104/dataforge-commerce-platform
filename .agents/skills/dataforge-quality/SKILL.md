---
name: dataforge-quality
description: Gate DataForge changes with repeatable tests, data contracts, falsification checks and honest evidence logs before phase completion.
---

# Quality/release gate

1. Read touched modules plus `docs/releases/v1.0-local.md`. Never infer passes.
2. Prefer focused reproducible tests: Python pytest; Postgres integration with `RUN_POSTGRES_TESTS=1`; Power BI Desktop screenshot/metrics check by user where GUI required.
3. Include adversarial cases: duplicate item IDs, missing orders, SCD2 overlap, split payments, refund > order item net value, rerun invariance, partial failure.
4. Record command, exit code, test count, environment and expected vs actual in the active release record. Mark SKIP/UNVERIFIED explicitly.
5. Reconcile generated fixture math with SQL, clarify expected exceptions for real external sources.
6. Do not ship if critical data correctness or security fail. A non-blocking BI preview inability remains documented rather than 'passed'.
