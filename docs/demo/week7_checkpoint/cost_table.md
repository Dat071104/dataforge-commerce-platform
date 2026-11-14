# Cost evidence for the Week 7 demo

This is an evidence table, not a billing export. All amounts are USD. Planned list-price estimates, observed usage estimates, incremental lane spend, and settled billed spend are separate quantities.

| Cost item | Amount / rate | Evidence and interpretation |
|---|---:|---|
| Settled billed spend for the whole project | **Unknown** | No final billing export is present in the repository. Earlier usage views and list-price estimates are not an invoice; account-wide free-tier and credit use are unknown. |
| New GCP spend from Lane D / Lane E | **USD 0 observed** | The lanes made no GCP calls or resource changes. This only describes incremental spend from these lanes; it does not establish a zero project bill. |
| Planned C4 fixed infrastructure subtotal | **USD 4.985947 / 120 hours**; approximately **USD 0.04155/hour** | Lower-bound planning estimate from [Lane C](../../process/lanes/c.md). It excludes variable NAT processing, egress, logging, and staging, so it is not a worst-case estimate or actual spend. |
| Planned C7 managed Spark compute plus illustrative shuffle | **USD 0.720548** | Planning estimate from [Lane C](../../process/lanes/c.md). GCS and network bounds remain incomplete. No managed Spark batch was submitted. |
| Historical Mini3 Cloud Run + BigQuery compute subtotal | **Approximately USD 0.095 gross list-price estimate** | Based on 48 Cloud Run executions and 2,149,580,800 successfully billed BigQuery bytes in the retained [cost and cleanup report](../../cloud/week7/closure/iam_cost_cleanup.md). This is not a per-run rate or settled bill. It excludes uncertain storage, network, API, Workflow, Monitoring, and logging charges and precedes account-level free usage. |
| Weather artifact storage estimate | **Approximately USD 0.028/month only if the billing-account free allowance is exhausted** | The retained report measured 283.04 MiB of unique compressed image blobs across 21 digests. Other repositories and projects share the free allowance, so actual charged storage is unknown. |
| Current running cloud resource cost per hour | **Unknown** | No live inventory was performed for this lane; cached gcloud reauthentication was blocked in the D-pack checklist. Do not infer a running VM or report a rate without fresh authorized inventory and pricing evidence. |

## Safe demo wording

Say: “The retained Mini3 compute usage has an estimated gross subtotal of about USD 0.095 before free usage and unpriced services. That is not the settled project bill. We did not create a VM or managed Spark batch in these release lanes. Current resource inventory and the final billed total are unverified.”

Do not say “the project cost USD 0,” “the VM costs USD 0.04155/hour in actual use,” or “the USD 10 target is a hard cap.” A budget alert reports usage; it does not stop spend.
