# Deferred engineering issue drafts

These are draft scopes for future planning. They are not GitHub issues and no issue was created. Week 8 has not started. Each item needs a separate scope and authorization review before implementation.

## Draft 1 — Week 8: local Kafka CDC learning path

**Why:** The syllabus introduces topics, partitions, offsets, consumer groups, Schema Registry, Debezium, and streaming state. Current DataForge work is batch-focused.

**Candidate scope:**
- Use a small synthetic PostgreSQL source and a local Docker Compose environment.
- Demonstrate Debezium CDC to Kafka, explicit topic/partition and offset handling, then one bounded consumer transformation to a local analytical table.
- Define a record schema and compatibility check; show replay and duplicate handling as at-least-once unless a specific transaction boundary is proved.
- Include deterministic fixture tests and a teardown/runbook.

**Acceptance evidence:** producer/consumer contract, offset/replay test, schema-evolution test, source-to-target reconciliation, one injected malformed event, resource-safe local startup/cleanup, and a brief architecture note.

**Non-goals:** production Kafka cluster, managed streaming service, claims of exactly-once across systems, or modification of accepted commerce tables.

**State:** <code>NOT_RUN</code>; outside the current P7.5 scope.

## Draft 2 — Week 9: terminal-failure observability and bounded failure matrix

**Why:** Existing tests and Week 7 live drills establish bounded correctness, but recurring operational alerting is not active and Airflow's current callback only logs locally.

**Candidate scope:**
- Define one terminal event schema with run/task identity, error class, severity, and dedupe key; exclude credentials, PII, routine no-op, and retry-in-progress outcomes.
- Add offline matching/format tests for transient retry, terminal failure, duplicate event, and successful run.
- Extend the failure matrix with representative schema, manifest, publication, timeout, and concurrency cases in local fixtures.
- Prepare a read-only runbook and expiry/disable steps for any future notifier.

**Acceptance evidence:** tests for inclusion/exclusion and dedupe; terminal failure recovery receipt; exact CI checks; documented operator response and retention.

**Approval boundary:** any GCP policy/channel creation, recurring notification, or email/Slack delivery requires new, specific approval for destination, count, duration, and cost. The one-time email authorization is consumed.

**State:** <code>PARTIAL</code> related testing exists; this new Week 9 deliverable is <code>NOT_RUN</code>.

## Draft 3 — Week 6 optional managed Spark comparison

**Why:** The local Spark lab is verified, but managed Spark remains a syllabus gap and was not authorized.

**Candidate scope:**
- First compare current managed-runtime options, minimum billing duration, quotas, storage/networking, logging, and IAM using official sources.
- Select the smallest public TLC sample that reconciles exactly with the local Oracle.
- Define a single bounded batch, max concurrency one, finite timeout, no automatic retry, isolated output prefix/dataset, exact cleanup steps, and a maximum spend before any run.
- Preserve a local-versus-managed comparison without promising a speedup.

**Acceptance evidence:** explicit sample/schema contract, local Oracle parity, actual job ID and runtime result, plan/log evidence, observed resource cleanup, and a separate reviewer decision.

**Approval boundary:** no managed job or resource creation until the user approves the exact runtime, target, maximum planned spend, and teardown.

**State:** <code>CLOUD_SPARK_NOT_AUTHORIZED</code>; no managed batch was submitted.

## Draft 4 — Hosted Airflow feasibility, only if mentor requires it

**Why:** Airflow has run once in local Docker against the real GCP data plane. It is not hosted, and there is no recurring Airflow schedule. Workflows already demonstrates bounded GCP orchestration.

**Candidate scope:**
- Ask the mentor whether a hosted Airflow scheduler is required for the checkpoint.
- Compare the accepted hybrid path, a time-bounded single-node Airflow deployment, and a managed orchestration service with cost/operations estimates.
- If a deployment is required, design least privilege, keyless identity, private access, metadata storage, finite runtime, one scheduler only, monitoring, stop timer, and destroy plan before any apply.
- Capture an actual scheduled DagRun and retry transition only after independent authorization; no long-lived operation claim from a one-run demo.

**Acceptance evidence:** mentor requirement, reviewed architecture and spend limit, reviewed Terraform plan with no unexpected deletes, one verified run, cleanup receipt, and separate cost/operability review.

**Approval boundary:** hosted scheduler, VM/Composer, networking/IAM, or recurring schedule requires explicit approval for exact target, duration, permissions, and spend.

**State:** <code>MENTOR_CONFIRMATION_PENDING</code>; no hosted Airflow resource is deployed.
