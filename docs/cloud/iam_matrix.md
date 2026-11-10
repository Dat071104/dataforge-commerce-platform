# P7.1 IAM matrix — live isolated target

**Project:** `dataforge-p7-lab-d0f725` (`955038620072`)
**Evidence:** [live foundation inventory](evidence/live_foundation_inventory.json), [IAM positive/negative checks](evidence/iam_live_verification.json), [reviewed Terraform plan](evidence/reviewed_plan_summary.json)

| Principal | Resource scope | Role / status | Purpose and boundary |
|---|---|---|---|
| Verified human deployer/uploader | Project | Existing Project Owner; not granted by this stack | Performed the one-time foundation deployment and source uploads. This identity is privileged; the deployment does not claim least-privilege administration. |
| Optional local transfer principal (`transfer_member`) | Bucket, project, `staging` dataset | **Unset; no transfer grants created** | Avoids redundant bindings to the existing Project Owner. Configure only if a distinct uploader is approved for a later workflow. |
| `dataforge-runtime` service account | One Bronze bucket | `roles/storage.objectViewer` + `roles/storage.bucketViewer` | Object read and bucket metadata/location checks, scoped to `dataforge-p7-lab-d0f725-bronze`. Live object read and SHA-256 comparison passed. Bucket Viewer is the predefined metadata role used by the adapter; recheck its status if the provider role catalog changes. |
| `dataforge-runtime` service account | Project | `roles/bigquery.jobUser` + `roles/serviceusage.serviceUsageConsumer` | Run BigQuery jobs and use the explicit project as quota project. No project Owner/Editor grant. |
| `dataforge-runtime` service account | `staging` dataset only | `roles/bigquery.dataEditor` | Create and write disposable raw/typed tables. The role permits table update/delete; staging tables expire after seven days. Live query succeeded. |
| `dataforge-runtime` service account | `silver` / `gold` | **None** | No Week-4 write permission. Runtime Gold table listing returned HTTP 403. |
| Verified operator | `dataforge-runtime` service account resource only | `roles/iam.serviceAccountTokenCreator` | Applied for keyless impersonation during runtime verification and retained for reproducible identity checks. It is not project-wide and no service-account key was created. Its holder can act with the runtime account's existing permissions; remove if no longer needed. |

## Live verification

- Bucket metadata reports the expected target project, `US-CENTRAL1`, uniform access enabled, public access prevention enforced, and no public IAM members.
- Runtime GCS read returned HTTP 200 and matched the manifest SHA-256. The tested GCS permission was `storage.objects.get`; the runtime has no object create/delete grant.
- Runtime BigQuery job returned eight rows and eight unique keys. Anonymous access to the private object returned HTTP 403; listing Gold tables as runtime returned HTTP 403.
- No service-account key was created. The target project has the required Service Usage, Cloud Resource Manager, Storage, BigQuery, IAM, and IAM Credentials APIs enabled; the live inventory lists BigQuery dependency APIs as well.

The project is linked to the existing active Free Trial without a billing upgrade. This does not make the Owner least-privileged, guarantee trial coverage for every operation, or cap spending. The operational usage target is USD 10; final usage and cost evidence is tracked separately.

References: [BigQuery load permissions](https://docs.cloud.google.com/bigquery/docs/batch-loading-data), [BigQuery role scopes](https://cloud.google.com/iam/docs/roles-permissions/bigquery), [Cloud Storage uniform bucket-level access](https://docs.cloud.google.com/storage/docs/uniform-bucket-level-access), [Storage IAM roles](https://docs.cloud.google.com/storage/docs/access-control/iam-roles), [Terraform Google provider quota configuration](https://github.com/hashicorp/terraform-provider-google/blob/main/website/docs/guides/provider_reference.html.markdown).
