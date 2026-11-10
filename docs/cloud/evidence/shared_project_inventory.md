> HISTORICAL: this shared target was superseded by the user before deployment. The current isolated target is in [target.json](../target.json).

# Approved project: pre-existing resources (read-only)

**Checked:** 2026-11-09, before DataForge deployment.

The approved project `kinetic-magnet-512406-m3` is shared with an existing SaigonBite deployment. It is not an empty project. This inventory does not authorize changes to those resources.

| Resource | Observed state | DataForge boundary |
|---|---|---|
| Compute Engine `saigonbite-vm` | `RUNNING`, `e2-medium`, `asia-southeast1-b` | Not imported, stopped, resized, deleted, or managed by DataForge |
| GCS `saigonbite-backups-kinetic-magnet-512406-m3` | Existing bucket, `ASIA-SOUTHEAST1` | No object reads/writes or policy changes |
| Existing default Compute Engine and SaigonBite service accounts | Listed; neither disabled | Not modified or granted DataForge access |
| BigQuery datasets | None listed | Proposed DataForge `staging`, `silver`, `gold` names do not conflict |
| Cloud Run services/jobs and Cloud Asset Inventory | Read attempts returned `403 SERVICE_DISABLED` | No API enabled to expand this inventory |

The current project IAM contains an Owner, an Editor, and existing Google-managed service-agent bindings. These were inspected as role/member counts only in the public receipt; personal principal names are excluded. Project-level tests confirmed deployer access to create the approved resources and update IAM. Tests on a project are not proof of permissions on a bucket that does not yet exist.

The Console shows an active Free Trial with positive remaining credit and 72 days remaining. The linked project is `ACTIVE`; billing is linked and enabled. The current-month billing report shows net zero after savings, with pre-existing compute/network usage. The report is shared-project usage, not DataForge-attributable cost. No personal credit balance, billing-account identifiers, or screenshots are retained here.

The user's prompt says to stop on unexpected services. Accordingly, the existing VM/bucket must be disclosed and the shared-project boundary confirmed before any DataForge cloud mutation. Source preparation, local validation, and creation of a reviewable Terraform plan may continue.
