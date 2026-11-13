# Mini-project 3 controlled failure notification

**Status:** delivered and user-confirmed on 2026-11-12. The receipt deliberately omits the destination address.

## Controlled test

- Workflow execution: 355edf21-c024-4749-af17-c8e53c746581.
- Test mode: manual, one controlled failure after dbt build/tests and before publication.
- Failure marker: DATAFORGE_WEATHER_CONTROLLED_ALERT_TEST; the temporary Monitoring policy matched only this controlled event at ERROR severity and notified on incident opening.
- Monitoring incident: projects/dataforge-p7-lab-d0f725/alerts/0.oexdkwiozn6y.
- Incident opened: 2026-11-12 09:47:11 UTC.
- Delivery: the user confirmed the one approved email arrived. No second test was sent.
- Cloud Logging notification delivery errors: zero observed.

The controlled run wrote a FAILED ledger row with error category controlled_failure_test. It stopped before Gold publication. The Gold pointer remained at version 4 with the Airflow run as its current publisher; the published view still had 3 rows for 3 provinces and zero invalid metrics.

## Cleanup and limits

The temporary email channel and failure-only alert policy were deleted after the single delivery. A final Monitoring API list returned zero notification channels and zero alert policies. No recurring alert remains. The Monitoring API remains enabled because its Terraform service resource is configured with disable_on_destroy = false.

The notification receipt records the user's delivery confirmation; it is not an independent Gmail API receipt. The destination was explicitly approved by the user and is not included in this repository.
