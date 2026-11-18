---
name: dataforge-fault-injection
description: Run or extend the DataForge Week 9 fault-injection matrix (F01-F15, F-T1, F-N0) safely on isolated datasets and record detection evidence for Mini-project 4, including the game-day drill.
---

# Fault injection (Mini-project 4)

1. Faults are defined only in `docs/week9/failure_modes.md`. A new fault is a new catalog row first (ID, injection point, expected detector check_id, severity, action), then code.
2. Inject only into `w9_drill`, `dbt_ci_pr_<n>` or local fixtures. Copy a minimal clean slice (for example 7 dates x 3 provinces) from prod with read-only access, then mutate the copy. Never mutate prod tables or prod GCS prefixes.
3. One fault per run. Reset to the clean slice between faults so results are independent.
4. Assert all four for every fault: detected by the expected check_id; severity matches; action matches (block / warn / no-op); for P1, the published-Gold hash is unchanged. Record injected_at, detected_at and alert received_at (MTTD).
5. Always include **F-N0** (clean data) in the same matrix. It must produce zero alerts and zero P1/P2 rows. A matrix without the negative control is invalid.
6. Never relabel a fault as "not applicable" to make the matrix green. A missed fault is `DQ_MISS`: fix the gate.
7. Code faults F13-F15 are PR fixtures on throwaway branches. Expected result: the named required check is red with the expected message. Delete the branch afterwards.
8. Deliberate alert emails count against Addendum F row AF7 (at most 6 in Week 9, counted from Monitoring incidents). Slack messages are not capped but must be deduplicated.
9. Output `fault_matrix_report.md` with columns: fault, injected_at, detector, detected_at, channel, received_at, action, gold_hash_before, gold_hash_after, PASS/FAIL, evidence level (unit / CI harness / live GCP).
10. Game day: the injector and the responder are different agents. The injector writes a sealed record outside the repo. The responder sees only alerts, `dq_results` and runbooks, and never sees the seed until the postmortem draft is written.
