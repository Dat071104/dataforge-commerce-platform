---
name: dataforge-dataops-ci
description: Build or review DataForge Week 9 CI/CD - keyless Workload Identity Federation, PR-scoped BigQuery datasets, slim dbt build, contract and PII checks, toolbox image, cleanup, required checks and CI evidence.
---

# DataOps CI/CD (Week 9)

1. Auth: GitHub OIDC to a WIF provider whose attribute condition uses the **numeric** repository ID and owner ID (not only names), then service-account impersonation. No JSON keys, ever. Fork PRs get no OIDC token: cloud jobs skip with an explicit notice, never a silent pass.
2. PR dataset `dbt_ci_pr_<number>`: default table expiration 24 h, labels `week=w9,pr=<n>`, dropped by a `pull_request: closed` job. The dbt profile sets `maximum_bytes_billed` (1 GiB) and job timeouts.
3. Slim CI: `dbt build --select state:modified+ --defer --state <prod-manifest-dir>`. The prod manifest is the latest main CD artifact. If it is absent, build the weather selection fully (the data is tiny) and say so in the PR comment.
4. Job order: lint, unit, contract lint + breaking check, PII guard, dbt build, G1 gate, fault matrix, data-diff, PR comment. Every job has `timeout-minutes`, `concurrency` with cancel-in-progress, and minimal `permissions:` (`id-token: write` only where needed).
5. Pin actions by commit SHA with a version comment. Pin Python dependencies with a lockfile. Build the toolbox image in Actions (gzip layers, never zstd). The same image runs CI and local.
6. Never echo secrets or tokens. Mask outputs. Run gitleaks or a secret scan before every push.
7. GitHub only through `gh`/REST. One blocking wait per run. The company Wi-Fi blocks github.com: on a port 443 failure, ask the user once to switch to 5G, then batch all GitHub work.
8. Add a check to the `main` ruleset only after it has passed once on main.
9. Record for each workflow: run ID, head SHA, conclusion, duration, bytes billed (from the PR comment) and artifact names.
10. Workers only write Terraform and produce `plan` output. The integrator reviews and runs `apply`, with the state key `week9_dataops` in the C10 backend bucket.
