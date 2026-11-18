# S11 Terraform drift RCA — 2026-11-18

## Finding
After the approved 3-resource targeted destroy, a read-only full plan in the shared dev state proposed 3 additions and 1 change: it would recreate both Airflow job-level execution-reader bindings and their custom role, and change weather-dbt from live digest 3719ed35 back to c6a2a187. No part of that full plan was applied.

## Root cause
The three execution-reader resources use `count = var.week7_weather_enabled`; the local ignored `terraform.tfvars` still sets that broad integration flag to true. The same local tfvars still pins the weather-dbt input to c6a2a187, although E2 deployed 3719ed35. The signed S11 removal was therefore live but not represented by the desired Terraform inputs.

## Scope and evidence
The role and both job-level bindings were removed by a saved plan containing exactly 0 add / 0 change / 3 destroy. A read-only project IAM policy check found no project-level D2 binding. Shared job-runner and operation-reader roles were not targeted. The full plan showing the drift is `evidence/s11-dev-post-cleanup-full-plan-20261118.log`; targeted plan/apply evidence is in `evidence/s11-execution-reader-destroy-plan-20261118.log` and `evidence/s11-execution-reader-destroy-apply-20261118.log`.

## Corrective action
Add a dedicated false-by-default variable for only the temporary execution-reader role and its two Airflow job bindings. Update the local ignored weather-dbt image input to live digest 3719ed35. Then run a read-only full plan and require zero changes to the preserved Cloud Run jobs and unrelated Week-7 resources before committing any configuration/evidence update.
