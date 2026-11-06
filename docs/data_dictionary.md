# Data dictionary

This dictionary describes the PostgreSQL `raw`, `dw` and `analytics` schemas observed on the seed-42, 3,000-order synthetic fixture. Physical types are PostgreSQL `information_schema` types. The observed fixture counts are in [`data_quality_and_reconciliation.md`](data_quality_and_reconciliation.md); they are not fixed schema expectations.

## Raw source tables

Each raw table is a complete input snapshot. Source identifiers are text. The listed grain/key is the source contract used by the loader.

| Table | One row per / logical key | Fields |
|---|---|---|
| `raw.orders` | order / `order_id` | `order_id text`; `customer_id text`; `order_date date`; `province_id text`; `status text` |
| `raw.order_items` | order line / `order_item_id` | `order_item_id text`; `order_id text`; `product_id text`; `quantity integer`; `unit_price numeric`; `discount_pct numeric` |
| `raw.payments` | payment event / `payment_id` | `payment_id text`; `order_id text`; `payment_date date`; `amount numeric`; `status text`; `method text` |
| `raw.returns` | return event / `return_id` | `return_id text`; `order_item_id text`; `return_date date`; `refund_amount numeric`; `status text` |
| `raw.shipments` | shipment / `shipment_id` | `shipment_id text`; `order_id text`; `ship_date date`; `delivery_date date NULL`; `status text`; `carrier text` |
| `raw.customers` | current customer row / `customer_id` | `customer_id text`; `signup_date date`; `province_id text`; `segment text` |
| `raw.customer_segments` | customer segment interval / (`customer_id`, `valid_from`) | `customer_id text`; `segment text`; `valid_from date`; `valid_to date NULL`; intervals are start-inclusive/end-exclusive |
| `raw.products` | product / `product_id` | `product_id text`; `category text`; `subcategory text`; `base_price numeric`; `unit_cogs numeric` |
| `raw.geography` | province / `province_id` | `province_id text`; `province text`; `region text` |
| `raw.inventory` | product/date snapshot / (`snapshot_date`, `product_id`) | `snapshot_date date`; `product_id text`; `quantity_in_stock integer`; `reorder_point integer` |
| `raw.weather_daily` | province/day / (`province_id`, `observation_date`) | `province_id text`; `observation_date date`; `precipitation_mm numeric NULL`; `temp_max_c numeric NULL`; `source text` |

## Gold dimensions

| Table | Grain / key | Column definitions |
|---|---|---|
| `dw.dim_date` | calendar day / `date_key` (`YYYYMMDD`) | `date_key integer` deterministic key; `calendar_date date`; `year integer`; `month integer`; `month_start date`; `quarter integer` |
| `dw.dim_customer` | customer version / `customer_key` | `customer_key integer` persistent surrogate; `customer_id text` natural identifier; `segment text`; `valid_from date`; `valid_to date NULL`; `is_current boolean`; `signup_date date`; `geography_key integer`; `customer_region text`. Facts resolve one version as of order date. |
| `dw.dim_product` | product / `product_key` | `product_key integer` persistent surrogate; `product_id text`; `category text`; `subcategory text`; `base_price numeric`; `unit_cogs numeric` (current cost, not historically versioned). |
| `dw.dim_geography` | province / `geography_key` | `geography_key integer` persistent surrogate; `province_id text`; `province text`; `region text` |

## Gold facts

| Table | Exact grain / logical key | Column definitions |
|---|---|---|
| `dw.fct_order_item` | one order line / `order_item_id` | `order_item_id text`; `order_id text`; `order_date_key integer`; `customer_key integer` (SCD2 version); `product_key integer`; `geography_key integer`; `order_status text`; `quantity integer`; `unit_price numeric`; `discount_pct numeric`; `gross_item_value numeric = quantity × unit_price`; `discount_value numeric`; `net_order_value numeric = gross − discount`; `fulfilled_sales_proxy numeric` (net value only when delivered); `fulfilled_cogs_proxy numeric` (current unit COGS × quantity only when delivered). |
| `dw.fct_payment` | one payment event / `payment_id` | `payment_id text`; `order_id text`; `geography_key integer`; `payment_date_key integer`; `method text`; `status text`; `amount numeric`; `collected_amount numeric` (successful payments only; otherwise zero). |
| `dw.fct_return` | one return event / `return_id` | `return_id text`; `order_id text`; `order_item_id text`; `geography_key integer`; `return_date_key integer`; `status text`; `refund_amount numeric`; `completed_refund numeric` (completed refunds only; otherwise zero). |
| `dw.fct_shipment` | one shipment / `shipment_id` | `shipment_id text`; `order_id text`; `geography_key integer`; `ship_date_key integer`; `delivery_date_key integer NULL`; `carrier text`; `status text`; `transit_days integer NULL`; `late_over_3_days boolean NULL` (only evaluated for delivered shipments with usable dates). |
| `dw.fct_inventory_snapshot` | one product/date / (`snapshot_date_key`, `product_key`) | `snapshot_date_key integer`; `product_key integer`; `quantity_in_stock integer`; `reorder_point integer`. The source has no regional inventory grain. |
| `dw.fct_weather_daily` | one province/day / (`date_key`, `geography_key`) | `date_key integer`; `geography_key integer`; `precipitation_mm numeric NULL`; `temp_max_c numeric NULL`; `source text`. Synthetic records and API observations are explicitly labeled. |

## Analytics views

| View | Grain | Fields / interpretation |
|---|---|---|
| `analytics.vw_daily_sales` | order date | `order_date date`; `delivered_orders bigint`; `fulfilled_sales_proxy numeric`; `fulfilled_cogs_proxy numeric` |
| `analytics.vw_monthly_sales` | month | `month_start date`; `delivered_orders numeric`; `fulfilled_sales_proxy numeric`; `fulfilled_cogs_proxy numeric` |
| `analytics.vw_order_reconciliation` | one row per order | `order_id text`; `order_date_key integer`; `geography_key integer`; `ordered_net_value numeric`; `expected_collection_proxy numeric`; `collected numeric`; `completed_refunds numeric`; `collection_variance numeric`. Payment and refund facts are aggregated before the order-level join. No customer or product filter path exists. |
| `analytics.vw_delivery_weather` | one delivered shipment with available weather match | `shipment_id text`; `order_id text`; `carrier text`; `transit_days integer`; `late_over_3_days boolean`; `province text`; `ship_date date`; `precipitation_mm numeric`; `weather_source text`. This is descriptive association only. |

## Date roles

Order items use order date; payment events use payment date; returns use return date; shipments use ship date by default and delivery date only through an explicitly activated secondary relationship; inventory uses snapshot date; weather uses observation date. The `dim_date` range is generated to cover all event-date references in the loaded facts, not a multi-decade calendar.

## Grain safety

Never join order-item, payment, return and shipment source rows together and sum their measures: one-to-many fact joins multiply values. Aggregate each fact at its intended grain first. Synthetic split payments are expected; successful collections belong to payment date and delivered sales proxy to order date. See [`metric_contract.md`](metric_contract.md) for definitions and exclusions.
