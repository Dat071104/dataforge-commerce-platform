# Terraform post-teardown reconciliation (2026-11-18)

The shared dev-state cleanup first targeted only the two Airflow job execution-reader IAM members and their dedicated custom role (0/0/3). A read-only full plan then exposed that the broad weather-enabled flag would recreate those grants and that the ignored local tfvars still pinned weather-dbt to c6a2a187, which would revert the live E2 image digest.

A dedicated false-by-default input now gates only the execution-reader role and its two job bindings. The local ignored image pin is aligned to the deployed digest 3719ed35. A subsequent full dev plan reported no changes. No change was made to the shared job-runner or operation-reader roles.

The raw destroy plan contains principal identifiers and stays outside this evidence PR. See s11-terraform-drift-rca-20261118.md for the root cause.
