# Legacy project read-only service inventory

**Checked:** 2026-11-09 (Asia/Bangkok)
**Purpose:** Identify currently deployed services in the superseded project without changing its resources.
**Scope:** Read-only Cloud Run service/job checks plus supported service-list attempts. No project ID, billing data, URLs, principal names, or screenshots are stored here.

## Observed service

| Resource | Region | Observed state | Exposure / traffic |
|---|---|---|---|
| Cloud Run service `askbetter` | `asia-southeast1` | Ready; 100% traffic on revision `askbetter-00008-wjv`; maxScale 20; 1 vCPU / 512 MiB | Ingress `all`; IAM grants `roles/run.invoker` to `allUsers` |

This is a deployed, publicly invokable service. Its current instance count, request volume, billing, and data contents were not inspected. No URL or runtime identity was copied.

Cloud Run Jobs in `asia-southeast1`: **0 listed**. This check does not rule out jobs or services in other locations.

## Inventory coverage and limits

| Surface | Result |
|---|---|
| Cloud Asset Inventory | UNAVAILABLE; a project-wide asset search did not return an inventory |
| Compute Engine instances | NOT AUDITABLE; Compute Engine API is disabled for the legacy project |
| Cloud SQL instances | NOT AUDITABLE; Cloud SQL Admin API is disabled |
| GKE clusters | NOT AUDITABLE; Kubernetes Engine API is disabled |
| Cloud Functions | NOT AUDITABLE; Cloud Functions API is disabled |
| Dataproc clusters | NOT AUDITABLE; no region-wide inventory was returned |
| Billing / actual cost | NOT INSPECTED |

No APIs were enabled to complete the inventory. The checks above do not prove that other products or resources are absent.

## Safety record

- All commands were read-only inventory calls.
- No resource, IAM policy, billing setting, service, or project was changed or deleted.
- This is a historical inventory exception to the active-project documentation rule; it does not configure or target the legacy service for DataForge.
