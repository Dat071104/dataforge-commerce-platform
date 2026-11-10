# P7.1 file change manifest

Baseline: `e5d8dfba6d996c8a68913ce8113b8f6aeeea502b`; local feature branch `feature/p7-week4-gcp-foundation`. Commit/push/PR follow the independent final gate.

- `src/dataforge/cloud/`: opt-in contracts, integrity checks, immutable transfers, exact staging reconciliation, explicit isolated ADC, bounded request/job behavior and manifest receipts.
- `src/dataforge/cli.py`: network-free cloud preflight and default-dry-run cloud transfer; explicit execute flag.
- `tests/cloud/`: negative integrity/IAM/location/project/schema/retry/idempotence and credential-isolation coverage.
- `cloud/terraform/dev/`: pinned foundation, protected resources, restricted runtime IAM and optional service-account-scoped impersonation.
- `scripts/enter_dataforge_cloud.ps1`, `docs/cloud/target.json`: one current isolated SDK/project/state target; no credentials in source.
- `pyproject.toml`, `requirements-py311.lock`, `.github/workflows/ci.yml`: optional GCP client extra; CI runs offline tests with that extra installed.
- `README.md`, `docs/cloud/`: concise current status, syllabus mapping, actual deployment/job/integrity/IAM/cost/drift receipts, cleanup and future work.
- `.gitignore`: excludes private state/plans/credentials/provider cache/local auth troubleshooting; `docs/releases/v1.0-local.md` records follow-on checks without changing the original local verdict.

Excluded from publication: credential databases/ADC, OAuth codes/tokens, private billing/organization records, screenshots, raw sensitive logs, Terraform state/plans/tfvars, generated source/Parquet/workbooks, and the existing local PostgreSQL volume. Public receipts contain synthetic-data digests and resource/job metadata only.
