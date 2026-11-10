# ADR-002 — One region for synthetic GCS and BigQuery

**Status:** Applied and live-verified for synthetic Week-4 data.

## Decision

Use `us-central1` for the GCS Bronze bucket, BigQuery `staging`/`silver`/`gold` datasets, and adapter requests. The live bucket reports `US-CENTRAL1`; all three datasets report `us-central1`. The adapter rejects a location mismatch before upload, and the live inventory confirmed location parity.

This deliberately simple policy avoids cross-location transfer paths and keeps regional reasoning explicit. BigQuery dataset location is fixed at creation, so future location changes require a separate migration plan.

## Evidence and boundary

- The live foundation inventory confirms the bucket and all datasets in the intended region.
- All 11 synthetic source transfers and all 11 safe reruns passed using that co-located target.
- This decision does not establish Vietnamese data residency, approve customer/personal data movement, or imply that GCP satisfies an Azure/Fabric-specific mentor checkpoint.
- Before proposing real or residency-sensitive data, review policy, data location requirements, service availability, and current regional SKUs. The current operational cost target is USD 10, not a guarantee.

## References

- [BigQuery locations and Cloud Storage colocation](https://docs.cloud.google.com/bigquery/docs/locations)
- [BigQuery dataset locations are immutable after creation](https://docs.cloud.google.com/bigquery/docs/datasets-intro)
