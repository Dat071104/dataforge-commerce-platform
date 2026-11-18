# Week 9 local fault matrix

This report uses captured fixtures and local WAP files only. No alert was sent and no BigQuery dataset was accessed.

| fault | run_id | manifest_path | as_of_date | injected_at | detector | detected_at | channel | received_at | action | gold_hash_before | gold_hash_after | result | evidence |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| F01 | f01-214450217930 | tests\week9\evidence\w9_drill\quarantine\f01-214450217930\manifest.json | 2026-11-18 | 2026-11-18T14:44:43Z | G1.LANDING.PROVINCE_ID_NOT_NULL | 2026-11-18T14:44:50Z | NOT_ATTEMPTED (local fixture) | NOT_ATTEMPTED | BLOCK | ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798 | ad79df00245dcdd0a909e08093fe70e02c07884e65dce445d2f3dc5f9114e798 | PASS | unit (local captured landing fixture) |

Counts: {"FAIL": 0, "PASS": 1, "UNVERIFIED": 0}
