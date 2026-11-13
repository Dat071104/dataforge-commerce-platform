# Week 7 Cloud Ops — prepared IaC and live-operation gate

This directory records the bounded Phase 2 design for C2–C4, C7–C11. The Terraform roots are code only: this lane ran no Terraform plan/apply, API enablement, state migration, secret creation, Artifact Registry policy application, VM creation, or Dataproc batch. Resource toggles default off. `terraform` is unavailable in the current environment, so provider formatting/schema validation remains an explicit CI/unblock item before any plan or live action.

## Resource roots

- `cloud/terraform/week7_ops/` owns the long-lived C2 USD 20 budget and C3 failure policies under the `week7/ops` state prefix.
- `cloud/terraform/airflow_vm/` owns only the short-lived C4 VM/network and C8 VM secrets under `week7/airflow-vm`; this separation lets teardown remove the VM and secrets while retaining the budget and alert policies. Its empty GCS backend must use an ignored `backend.hcl` with that distinct prefix.
- `cloud/terraform/state_backend_bucket/` is the C10 bucket bootstrap root. It creates a dedicated bucket with uniform access, public access prevention, versioning, and `deletion_policy=PREVENT`. Its initial state is local until the bucket is verified and the operator migrates that root too. `cloud/terraform/dev/versions.tf` now declares an empty GCS backend block for the existing dev root; its backend must be initialized with a verified, separate prefix and `terraform init -migrate-state` only after backup.
- `cloud/terraform/dev/` contains the C11 cleanup-policy draft on the Week-7 Artifact Registry repository. `week7_artifact_cleanup_dry_run` defaults to `true`; the explicit live job digests are seeded from the latest retained read-only receipt and must be refreshed before review.
- `labs/spark_nyc_taxi/managed/` contains a Dataproc Serverless driver that reuses the local Week-6 quality/aggregation functions, a separate local oracle, a worst-case cost guard, and a submit wrapper that defaults to plan-only.

## Phase 4 prerequisites and sequence

1. Dot-source the isolated project context in every PowerShell session that calls `gcloud`: `. D:\DATA_ENGINEER\DataForge\scripts\enter_dataforge_cloud.ps1`. Verify the active project is `dataforge-p7-lab-d0f725`; never use the unrelated default project.
2. Refresh R1 inventory. The earlier read found `compute.googleapis.com` disabled, so VM/disk/firewall inventory is unknown. Confirm the current billing-account ID, whether `monitoring.googleapis.com` and `logging.googleapis.com` are already enabled, the exact Cloud Run image digests, the VM service account bindings, and a non-overlapping VPC subnet before any apply. C1 does not authorize self-granting IAM.
3. Back up each local Terraform state before C10. Create the dedicated versioned state bucket through the bootstrap root, verify uniform access and public access prevention, then create ignored backend configs with distinct `dev`, `week7/ops`, and `week7/airflow-vm` prefixes.
4. Migrate the existing `dev` state only with the authorized C10 procedure: `terraform init -migrate-state -backend-config=backend.hcl`, then require `terraform plan` to show no changes. Initialize the two new Week-7 roots directly against their own prefixes. This lane did not run those commands.
5. Enable C2 only with the verified billing-account ID and C9 destination supplied outside version control. The budget resource fixes USD 20, actual thresholds 50/90/100%, and forecast threshold 100%; it disables default billing recipients and uses the approved notification channel.
6. Enable C3 only after reading a real Workflow failure log and a real Airflow `gcplogs` entry. Confirm the metric filters match the actual resource/label/payload shape and one terminal event yields one incident. Retries and `NO_NEW_BATCH` must not alert. Monitoring/Logging APIs are not enabled by this root; inspect their service state first.
7. Create C8 secrets only after the `airflow_vm` backend is secured; the C8 apply may precede VM creation. The provider write-only `secret_data_wo` attribute is used so payload bytes are not stored in state; provide the three generated values through protected local environment variables, never a committed `.tfvars`. Only the VM service account receives secret-level `secretAccessor` bindings.
8. Enable C4 only with the observed existing VM service account, a CI-built digest-pinned Airflow image, the Lane A runtime bundle/startup script, a subnet CIDR verified against live VPC inventory, and a UTC `destroy_by` timestamp no more than 120 hours out. The VM has no external IP; firewall ingress permits only IAP `35.235.240.0/20` on 22 and 8080. Cloud NAT provides outbound egress. Use IAP for SSH/UI and never open public ingress.
9. Keep the accepted Workflows weather schedule absent or paused. No new recurring schedule is created by these roots.
10. At teardown, destroy only the `airflow_vm` root, then disable/delete the C8 secrets. Leave the `week7_ops` root and its C2/C3 resources active until the user says to remove them.

## C4 gross list-price estimate

Rates were checked on 2026-11-13 from the official Google Cloud tables below. For the full 120-hour authorization window, on-demand list rates, and no free-tier or credits:

| Resource | Calculation | Estimate |
|---|---:|---:|
| `e2-medium` VM | USD 0.03350571/hour × 120 hours | USD 4.021 |
| 30 GiB standard persistent disk | USD 0.000054795/GiB-hour × 30 × 120 | USD 0.197 |
| Cloud NAT gateway | USD 0.0014/instance-hour × 120 | USD 0.168 |
| One public NAT IP | USD 0.005/hour × 120 | USD 0.600 |
| **Known subtotal** | Before processed NAT traffic, outbound transfer, logs, or temporary storage | **USD 4.986** |

The VM compute component alone is USD 4.021. The USD 4.986 known subtotal adds 30 GiB standard disk (USD 0.197), one-VM NAT gateway (USD 0.168), and one NAT IP (USD 0.600). The C4 cap is USD 8, so the global 80% stop threshold is USD 6.40; the subtotal leaves about USD 1.41 for transfer, logs, and other unpriced usage before the stop threshold. It is a **fixed-resource lower bound for the full 120-hour window**, not an expected-use estimate or a complete worst-case bound. Before apply, bound image/package downloads, job traffic, logging, and staging; if those additions take the estimate to USD 6.40 or more, reduce the design or stop. Official sources: [E2 VM pricing](https://cloud.google.com/products/compute/pricing/general-purpose?hl=en), [Persistent Disk pricing](https://cloud.google.com/compute/disks-image-pricing), [Cloud NAT/VPC pricing](https://cloud.google.com/vpc/network-pricing).

## C7 Dataproc Serverless cost gate

The proposed standard profile fixes 12 DCUs (4-vCPU/16-GiB driver plus two 4-vCPU/16-GiB executors), disables dynamic allocation and task retries, and sets a 30-minute TTL. The official `us-central1` standard rate is USD 0.06/DCU-hour, with standard shuffle storage at USD 0.000054795/GiB-hour. At the full TTL and two authorized attempts, compute is `12 × 0.06 × 0.5 × 2 = USD 0.72`; under an illustrative 10 GiB shuffle bound, both attempts add about USD 0.00055. These are compute/shuffle bounds only, not a pre-submit total-cost check.

That subtotal excludes GCS staging/output storage and network transfer. The USD 5 C7 cap has an 80% stop threshold of USD 4.00. Run `python labs/spark_nyc_taxi/managed/preflight.py` with the measured shuffle bound and an official-price upper bound for GCS/network before either submission. Missing inputs or a total at/above USD 4.00 block submission. No source file was downloaded or staged and no Dataproc batch was created in this lane. The pinned local Spark base image was not cached; no external Docker pull was attempted, so the existing Docker fixture suite was not run. Official sources: [Managed Service for Apache Spark pricing](https://cloud.google.com/products/managed-service-for-apache-spark/pricing), [Dataproc Serverless batch submit flags](https://docs.cloud.google.com/sdk/gcloud/reference/dataproc/batches/submit/pyspark).

## C11 cleanup safety

The Terraform drafts keep at least five recent versions per Week-5/Week-7 package, explicitly keep six digest version IDs from retained receipts (two Week-5 and four Week-7 image references); refresh the set from the current job inventory before review, and delete only untagged versions older than 30 days. The historical Week-5 cleanup receipt is `BLOCKED_BY_TAG_IMMUTABILITY`: deleting tagged image `week5-20261110-r1` returned `FAILED_PRECONDITION`, so no tagged-delete rule is configured. Before C4, add the Airflow VM's CI image digest to the live-digest input. `cleanup_policy_dry_run` defaults to true. The provider's `most_recent_versions` rule counts package versions rather than filtering the five most recent tagged versions, so keep dry-run enabled until the fresh artifact inventory confirms the tag distribution and exact live digest names. If untagged versions can displace required tagged releases, add the necessary keep policy before disabling dry-run. Never remove a digest used by a live workload or receipt. Official provider reference: [Artifact Registry repository cleanup policies](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/artifact_registry_repository).
