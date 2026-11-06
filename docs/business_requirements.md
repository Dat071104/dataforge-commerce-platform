# Business requirements and metric boundary

## Purpose

DataForge is a local-first training project that demonstrates a small order-to-cash data pipeline for a fictional Vietnamese fashion retailer. The canonical commerce data is deterministic synthetic data. It supports pipeline, warehouse and report testing; it is not evidence about an actual business.

## Questions the Gold layer should answer

| ID | Business question | Gold output | Reporting date |
|---|---|---|---|
| BR-01 | How does delivered sales proxy change month over month? | `analytics.vw_monthly_sales` | Order date |
| BR-02 | Which categories and products contribute most to delivered sales proxy? | `dw.fct_order_item` + product dimension | Order date |
| BR-03 | How do first-time and returning delivered customers compare? | `dw.fct_order_item` + customer dimension | Order date; stable `customer_id` for first order |
| BR-04 | What share of delivered item lines have a completed return? | `dw.fct_order_item` + `dw.fct_return` | Return date for refund values; line rate uses item grain |
| BR-05 | What are delivered shipment transit days and late-delivery rates? | `dw.fct_shipment` | Ship date by default; delivery date for explicitly role-switched measures |
| BR-06 | Do successful payment events reconcile to the delivered-sales proxy by order? | `analytics.vw_order_reconciliation` | Order date for the order-level variance; payment date for collections |
| BR-07 | Which customer cohorts return for another delivered order? | `dw.fct_order_item` | First delivered order month, then order month |
| BR-08 | Which inventory snapshots are below their reorder point? | `dw.fct_inventory_snapshot` | Snapshot date; inventory is not region-specific |
| BR-09 | How do recorded weather observations align with shipment outcomes? | `analytics.vw_delivery_weather` | Ship date; descriptive correlation only |

## Metric contract

The detailed definitions and invariants live in [`metric_contract.md`](metric_contract.md). Key portfolio labels must retain these meanings:

- **Fulfilled sales proxy**: net order-line value for orders whose status is `delivered`. It is not accounting-recognized revenue.
- **Fulfilled COGS proxy**: delivered quantity multiplied by the current product unit cost. Historical cost is not versioned.
- **Collected payments**: amount from successful payment events, on payment date.
- **Completed refunds**: completed return-refund amounts, on return date.
- **Collection variance**: successful collections less the delivered-sales proxy, first aggregated by order. It is an order-date synthetic reconciliation control and does not net return-date refunds.
- **Late shipment**: delivered shipment with a non-null transit duration greater than three days. The threshold is a demonstration SLA.
- **Weather relationship**: descriptive, province-level association. It is not causal and weather location is not a route-level observation.

## Grain and filter requirements

Payment, return, shipment, order-item, inventory and weather facts remain at separate grains. Any cross-fact reconciliation aggregates each fact to one row per order before combining it. Power BI filters flow from dimensions to facts in one direction. The order-reconciliation view intentionally has no customer or product filter path. Regional security must not be applied to global inventory data.

## Non-functional requirements

- Deterministic synthetic generation and offline fixture-based tests.
- CSV schema validation, explicit quarantine, checksummed Parquet snapshots and run manifests.
- Local PostgreSQL 16 warehouse with auditable snapshot loads and repeatable mart builds.
- SQL metric checks and an independent Python `Decimal` reference calculation.
- No cloud deployment, paid service, remote publish or unapproved third-party data redistribution.
- An optional historical weather request is opt-in and carries its own source attribution and license conditions.

## Scope limits

There is no accounting ledger, recognized-revenue rule, tax or shipping-fee model, promotion-attribution rule, event-stream watermark, production SLA or causal weather design. The IVin Datathon source remains excluded while its reuse rights and source schema are unresolved.
