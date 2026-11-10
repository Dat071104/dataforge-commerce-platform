> HISTORICAL: captured before authentication recovery and selection of a new isolated project. Current status/target: docs/cloud/week4_acceptance.md and docs/cloud/target.json.

# P7.0 baseline and source receipt

**Captured:** 2026-11-09 (Asia/Bangkok)
**Scope:** Read-only repository, CI, artifact, and GCP preflight before implementation.

## Repository and release baseline

| Check | Evidence |
|---|---|
| Repository | `D:\DATA_ENGINEER\DataForge`; remote `https://github.com/Dat071104/dataforge-commerce-platform.git` |
| Starting branch / HEAD | `main`, `e5d8dfba6d996c8a68913ce8113b8f6aeeea502b` (`docs: record v1.0-local CI verification`) |
| Remote `main` | `git ls-remote origin refs/heads/main` returned the same SHA |
| Initial working tree | `git status --short --branch` was clean |
| Working branch | `feature/p7-week4-gcp-foundation` created locally; no push or commit |
| P6.2 release | `v1.0-local` remains `GO LOCAL`; no tag, release, PBIP, local financial SQL, or local DB volume was replaced |
| Latest GitHub Actions | DataForge CI run **#6** completed successfully on `e5d8dfb` on 2026-11-06; [workflow history](https://github.com/Dat071104/dataforge-commerce-platform/actions) |
| Existing release test totals | Historical record: 96 offline passed / 6 PostgreSQL skips; 102 PostgreSQL-enabled passed. These were not rerun before this change. |

## Actual local Parquet and manifest inspection

The complete active run is `1b8ab9513d624bbcba6692a6ea0818f6`, status `complete`, with 11 sources. A read-only CSV/PyArrow/SHA-256 audit found:

- Each of the 11 actual CSV SHA-256 values matched its active manifest and synthetic source marker.
- Every Parquet byte SHA-256 matched `bronze_sha256`; Parquet row counts and column order matched the active manifest/source CSV.
- All 11 sources recorded zero rejected rows. Current Parquet schemas store every field as a nullable Arrow string, including source dates and numeric values.
- The active run totals 16,259 rows across distinct grains and 235,910 Parquet bytes. The `geography` source has 8 rows and 2,378 bytes; it is the proposed first smoke input because it has low exposure and only string fields.
- Generated CSVs, manifests, and Parquet files are local-only and ignored by Git. No P7 cloud directory or receipt existed before this branch.

The local source contract is in `configs/sources.csv`; PostgreSQL logical types and grain are in `sql/schema/001_init.sql` and `docs/architecture.md`. This adapter rejects a schema drift and does not change the local reader or writer.

## GCP status probe (read-only)

- The Google Cloud Console School/Students profile showed the approved project `kinetic-magnet-512406-m3` and an active Free Trial with observed expiry 2027-01-21. Personal credit amounts, billing-account identifiers, account names, and screenshots are not recorded.
- A separate SDK configuration root is `%APPDATA%\gcloud-dataforge-p7`, profile `dataforge-p7-kinetic-magnet-512406-m3`. It has the approved project, `us-central1`, and the same quota project configured, but **contains no authenticated account**. The user-wide default gcloud configuration was left unchanged and is not used for DataForge.
- The user-wide gcloud principal differs from the School/Students Console identity and its project-read request failed. The default ADC token refreshed, but a read-only Resource Manager request using the approved project as quota project returned HTTP 403; ADC principal identity could not be resolved. No API, IAM, billing, or resource change was attempted.
- Console trial status was observed, but the project-to-billing link and enabled APIs were not independently verified through an authorized CLI/API identity. Region and bucket/dataset co-location are configured in source only; there are no live locations to inspect.
- Terraform 1.17.1 and Google provider 8.9.0 are available locally. The isolated Terraform workspace and plan receipts are recorded separately. No plan was applied.

## Data protection boundary

The ignored `.env` was not read. No source CSV, Parquet, manifest, PostgreSQL volume, PBIP local settings, Power BI workbook, or external dataset was changed. The adapter works from an explicitly selected complete active run and uploads only the selected source; it does not upload CSV files or local absolute paths.
