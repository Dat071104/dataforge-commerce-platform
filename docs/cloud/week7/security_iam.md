# Week-7 IAM and secret boundary

**Status:** Terraform policy applied and inspected; IAM/service-account receipt is [`security_iam_receipt.json`](security_iam_receipt.json). Cloud Run, Workflows, GCS, and BigQuery positive paths passed. No service-account keys exist. Direct impersonated negative `testIamPermissions` probes were not run; see the limitation at the end.

## Identities and grants

| Identity | Grants | Explicitly absent |
|---|---|---|
| `dataforge-week7-workflow` | Read the exact Bronze manifest object; create BigQuery jobs and read only `ops.week7_publish_events` plus `gold_week7.week7_publication_pointer`; run the existing Week-5 job and Week-7 dbt job with argument overrides through a custom role limited to `run.jobs.run` and `run.jobs.runWithOverrides` on those two jobs; read returned operation state through the project custom role containing only `run.operations.get`; act as those jobs' runtime identities; write workflow logs. | No bucket list/write, no BigQuery table writes, no job configuration/IAM updates, no project Owner/Editor, no service-account key. |
| `dataforge-week7-dbt` | BigQuery job creation and service usage; read Week-5 Silver, the Week-5 run/checkpoint tables, and the single Week-5 Gold control table; write only `dbt_week7`, `dbt_week7_full`, `gold_week7`, `ops.week7_publish_lock`, and `ops.week7_publish_events`. | No Week-5 Silver/Gold writes, no source upload, no Cloud Run/Workflows/Scheduler invocation, no project Owner/Editor, no service-account key. |
| `dataforge-week7-scheduler` | Temporary identity for one paused-by-default `NO_NEW_BATCH` trigger test; custom project role contained only `workflows.executions.create`. | Identity, role, and job were removed after one forced run. No Cloud Run execution, BigQuery jobs/data access, workflow updates, project Owner/Editor, or key. |
| `dataforge-week7-ci-compile` | BigQuery job creation, service usage, and metadata viewing on the Week-5 source/control datasets plus the Week-7 candidate datasets. It has no table-data viewer or writer permissions. | No Cloud Run/Workflows/Scheduler access, no source-table row reads, no table writes, no project Owner/Editor, no service-account key. |

The CI identity uses Google Workload Identity Federation. Its provider requires GitHub repository ID `1446796465`, owner ID `242334093`, `event_name=push`, `ref` equal to `main` or under `refs/heads/feature/p7-`, and the `week7-ci.yml` workflow file. The GitHub Action grants `id-token: write` only to the compile job. Pull-request jobs, including fork PRs, receive no GCP identity; the compile status is produced from the same trusted branch commit before it is opened as a PR. No long-lived token or key is stored in GitHub or the repository.

The provider's attribute condition is reviewed independently and stored in Terraform. The temporary Scheduler caller used a small project custom role because the pinned Terraform Google provider does not expose a workflow-specific IAM member resource. That role contained only `workflows.executions.create` and was removed with the Scheduler identity after the forced no-op receipt. The Workflow identity's job-run role contains only `run.jobs.run` and `run.jobs.runWithOverrides`, bound separately to the two approved jobs; `run.operations.get` is a separate read-only project permission required to await the returned operation. A table-scoped `roles/bigquery.dataViewer` binding lets Workflows check the pointer's currentness flag after publication; it has no table write permission.

## Data and publication boundary

- Workflows verifies an immutable GCS manifest generation before invoking Week 5.
- The Week-5 service account retains its accepted role set and continues to publish only its Week-5 Silver/Gold/checkpoint state.
- Week-7 dbt writes candidate relations to its isolated datasets and immutable run versions to `gold_week7`. The publication pointer advances only after tests and reconciliation pass.
- Lease acquisition clears `publication_is_current`. The public view filters to a true flag, so stale or unvalidated Gold returns no current rows; successful publication sets the new pointer and restores currentness in one transaction. The Workflow identity can read the singleton pointer to verify the flag but cannot mutate it.
- The Week-5 `ops.week5_run_events` table remains append-only by application convention; its existing dataset/table grants do not provide cryptographic or database-enforced immutability. The Week-7 event ledger has the same IAM limitation for its writer.
- Week 4/5 Terraform resources, tables, source objects, and checkpoint rows are not deleted or rewritten by Week 7. All new Week-7 datasets and control tables have deletion protection/retention policies.

## Credentials and log handling

Local GCP access uses the isolated `dataforge-p7-lab-d0f725` ADC configuration. Cloud Run uses attached keyless service accounts. CI exchanges a short-lived GitHub OIDC token for the read-only compile identity. The repository ignores local `.env`, ADC files, local dbt profiles, Airflow state, Terraform state, and generated dbt artifacts; the Docker context excludes them as well.

Logs and `ops.week7_publish_events` record workflow run ID, batch ID, manifest generation, run mode, sequence bounds, status, dataset, row count, checksum, pointer revision, duration/error code where available. They do not include tokens, service-account JSON, local database passwords, customer secrets, or raw manifest contents.

## Negative checks to record

The applied-policy inspection verified the custom role permission lists, job-scoped bindings, pointer read binding, enforced public access prevention, uniform bucket access, no public bucket members, zero user-managed keys for the Week-4/5/7 runtime and Week-7 CI identities, and absence of the Scheduler job. Successful live Workflows also exercised the manifest reader, job runner, operation reader, event ledger reader, and pointer reader.

Direct negative `testIamPermissions` probes under impersonated Workflow/dbt/Scheduler identities were not run because this execution did not grant token-creator access for those identities. Based on the applied IAM policy, the following permissions are absent:

1. Scheduler identity cannot execute either Cloud Run Job or run a BigQuery job.
2. Workflow identity cannot create GCS objects or mutate BigQuery tables.
3. dbt identity cannot write Week-5 Silver/Gold, read unrelated Week-4 source rows, or invoke Cloud Run/Workflows/Scheduler.
4. CI identity cannot read table data or mutate any BigQuery table, and a pull-request or fork OIDC token is rejected by the provider condition.
5. Anonymous GCS access remains denied, and no service-account key exists.

The Scheduler job is absent after the forced `NO_NEW_BATCH` test; see [`scheduler_cleanup_receipt.json`](scheduler_cleanup_receipt.json). The Cloud Storage bucket had public access prevention enforced and no `allUsers`/`allAuthenticatedUsers` IAM member at verification time.
