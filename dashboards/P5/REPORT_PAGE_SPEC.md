# Report page and control specification

| Page | Visuals | Date role | Supported slicers |
|---|---|---|---|
| Executive Sales | Synthetic/proxy banner; fulfilled-sales and margin KPI cards; delivered orders; average order value card (VND millions, 2 decimals); monthly fulfilled-sales line; category bar | Order date | Date, order region, customer segment, product/category |
| Finance & Reconciliation | Payments, refunds, variance and split-payment-order cards; order-level reconciliation table; payment-event-by-order table | Payments: payment date; refunds: return date; variance: order date | Date and geography; no customer/product path for these facts |
| Operations & Weather | Late-delivery, P90 and return-line-rate cards; P90 by carrier; return-line-rate by category; late deliveries by delivery month; rainfall by observation month and province; weather-source label | Late/P90 by delivery date; weather by observation date; return-line-rate uses an order-date cohort and includes eventual completed returns | Date and region |

The inventory snapshot is deliberately omitted from the semantic model because it has no regional key. Fact tables remain at separate grains. Weather/late-shipment association is descriptive, not causal.
