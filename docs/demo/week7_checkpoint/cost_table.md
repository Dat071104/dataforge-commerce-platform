# Cost evidence for the Week 7 demo

This is an evidence table, not a billing export. All amounts are USD. Planned list-price estimates, observed usage estimates, incremental lane spend, and settled billed spend are separate quantities.

| Cost item | Amount / rate | Evidence and interpretation |
|---|---:|---|
| Settled billed spend for the whole project | **Unknown** | No final billing export is present in the repository. Earlier usage views and list-price estimates are not an invoice; account-wide free-tier and credit use are unknown. |
| New GCP spend from Lane D / Lane E | **No new spend observed** | Lane D created no GCP resource and Lane E made no GCP call. No lane-specific cloud cost was observed. This does not establish a zero project bill or a complete live inventory. |
| Planned C4 fixed infrastructure subtotal | **USD 4.985947 / 120 hours**; approximately **USD 0.04155/hour** | Lower-bound planning estimate from [Lane C](../../process/lanes/c.md). It excludes variable NAT processing, egress, logging, and staging, so it is not a worst-case estimate or actual spend. |
| Planned C7 managed Spark compute plus illustrative shuffle | **USD 0.720548** | Planning estimate from [Lane C](../../process/lanes/c.md). GCS and network bounds remain incomplete. No managed Spark batch was submitted. |
| Historical Mini3 Cloud Run + BigQuery compute subtotal | **Approximately USD 0.095 gross list-price estimate** | Based on 48 Cloud Run executions and 2,149,580,800 successfully billed BigQuery bytes in the retained [cost and cleanup report](../../cloud/week7/closure/iam_cost_cleanup.md). This is not a per-run rate or settled bill. It excludes uncertain storage, network, API, Workflow, Monitoring, and logging charges and precedes account-level free usage. |
| Weather artifact storage estimate | **Approximately USD 0.028/month only if the billing-account free allowance is exhausted** | The retained report measured 283.04 MiB of unique compressed image blobs across 21 digests. Other repositories and projects share the free allowance, so actual charged storage is unknown. |
| Current running cloud resource cost per hour | **Unknown** | No GCP resource is confirmed currently running. Inventory and actual hourly run-rate remain unverified because H5/R1 reauthentication and inventory are blocked. Retained resource definitions may exist; do not infer that no resources exist or report a VM rate without a fresh authorized receipt. |

## Safe demo wording

Say: “The retained Mini3 compute usage has an estimated gross subtotal of about USD 0.095 before free usage and unpriced services. That is not the settled project bill. Lane D did not create a GCP resource, and Lane E made no cloud call. No GCP resource is confirmed currently running, but inventory is unverified; the actual hourly run-rate and final billed total are unknown.”

Do not say “the project cost USD 0,” “the VM costs USD 0.04155/hour in actual use,” or “the USD 10 target is a hard cap.” A budget alert reports usage; it does not stop spend.
