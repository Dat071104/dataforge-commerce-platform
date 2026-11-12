# Week 7 dbt lineage

Generated from [`artifacts/manifest.json`](artifacts/manifest.json) after the seq-30 full pipeline. The graph contains only the deterministic Week 5 operational simulator's two source grains plus its control metadata.

```mermaid
flowchart LR
  so[Silver week5_orders] --> stg_o[stg_week5_orders]
  sp[Silver week5_payment_events] --> stg_p[stg_week5_payment_events]
  sc[ops.pipeline_checkpoints] --> stg_c[stg_week5_pipeline_checkpoints]
  se[ops.week5_run_events] --> stg_e[stg_week5_run_events]

  stg_o --> active[int_week5_active_orders]
  stg_o --> delivered[int_week5_delivered_sales_proxy_by_order]
  stg_o --> recon[fct_week7_order_reconciliation]
  stg_p --> current_payments[int_week5_current_payments]
  current_payments --> payment_control[int_week5_payment_control_by_order]
  payment_control --> collections[int_week5_successful_collections_by_order]
  payment_control --> recon
  stg_e --> batch_control[int_week7_batch_control]
  stg_c --> batch_control
  batch_control --> recon
  delivered --> recon
  recon --> receipt[fct_week7_build_receipt]
  stg_c --> receipt

  stg_o -. observation-time SCD2 .-> history[(week5_orders_history snapshot)]
```

The `int_week5_successful_collections_by_order` model is an independently aggregated control path. The reconciliation fact also uses `int_week5_payment_control_by_order`, which aggregates the payment grain before joining to order grain. This prevents multiple payment events from multiplying delivered sales.

Publication is a separate step after the dbt graph: a successful candidate/test run is copied into an immutable `gold_week7` version, then the compare-and-set pointer is switched. The public view filters on the pointer's `publication_is_current` flag and exposes no rows while the flag is false.
