# Metric Contract v0.1 (synthetic demo, NOT accountant-approved)

**Owner:** demonstration data owner. **Status:** PRE-APPROVED FOR SYNTHETIC FIXTURE ONLY. Real customer rules require Business Owner + Data Engineer sign-off.

| Metric | Source | Unit | Definition | Exclusions / caveats |
|---|---|---|---|---|
| Gross ordered value | fct_order_item | VND | sum(qty × price) | Includes canceled/processing orders |
| Net ordered value | fct_order_item | VND | gross less discount on all orders | Not revenue |
| Fulfilled sales proxy | fct_order_item | VND | net value of delivered order lines | Does not implement ASC/IFRS revenue recognition |
| Average order value | fct_order_item | VND | fulfilled sales proxy divided by distinct delivered orders in the current filter context | Display rounded to the nearest whole VND; category/product filters use the delivered orders represented in that filtered item-fact context |
| Fulfilled COGS proxy | fct_order_item | VND | qty × product unit_cogs on delivered lines | Historical unit costs not versioned |
| Collected payments | fct_payment | VND | successful payment events | Can occur on later date than order |
| Completed refunds | fct_return | VND | completed return refunds | Return-date metric; not same as reverse recognized sale |
| Collection variance | vw_order_reconciliation | VND | successful collected amount minus delivered fulfilled-sales proxy, summed at one row per order | Order-date metric; does not net return-date refunds; synthetic business assumption |
| Return line rate | order item + returns | % | unique delivered item lines with at least one completed return / all delivered item lines | An order-date cohort includes eventual completed returns regardless of return event date; not a unit return rate |
| Late over 3 days | fct_shipment | boolean | true when a delivery exists and delivery_date - ship_date > 3 days | 3-day threshold is hypothetical SLA |
| Late delivered shipment rate | fct_shipment | % | delivered shipments with transit_days > 3 / delivered shipments with non-null transit_days | Matches the delivered/non-null population in `sql/analysis/q05_delivery_p90.sql`; date role must be stated |
| P90 delivered transit days | fct_shipment | days | inclusive 90th percentile of transit_days for delivered shipments with non-null transit_days | SQL control is grouped by carrier; Power BI measure uses current report filters and delivery-date context |
| Gross margin proxy | order item | VND | fulfilled proxy - fulfilled COGS proxy | No shipping fees, taxes or overhead |

### Invariants

- `sum(fct_order_item.net_order_value)` matches order-line calculation from raw at matching grain.
- Split payments must be grouped before any join with line items.
- Synthetic generated delivered orders collect exactly the full net line amount; real data is not required to satisfy this contract.
- Order-date fulfilled sales, payment-date collections and return-date refunds are separate event-time series.
- The reconciliation view is one row per order and relates only to order date and order geography in the Power BI model; it has no customer/product filter path.
- Dimensional SCD2 joins never drop or multiply facts.
