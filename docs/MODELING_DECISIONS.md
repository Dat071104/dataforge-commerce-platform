# Modeling rationale: 3NF vs Kimball vs Snowflake vs OBT vs Data Vault

## Transactional 3NF (OLTP)

The source domain is normalized by business entities: orders, order_items, payments, shipments, returns, products and customers. This reduces update anomalies in transactional writes. It is not optimal for every interactive analytics query: tables have different grains and require careful joins.

## Dimensional Kimball star (chosen)

For analytics, business events become dedicated facts (one line item, one payment event, one shipment event, one return event, one product/date inventory snapshot). Small descriptive dimensions form star relationships. SCD2 customer versions make historical analysis as-of order date possible when change history is actually available. BI model one-to-many/single-direction.

## Snowflake (rejected for baseline)

Separating Geography into region/province tables could reduce dimension duplication but introduces a second BI relationship layer and complexity. Eight provinces here do not justify it; a single geography dimension is adequate. If enterprise master-data governance later requires normalization, evaluate trade-offs.

## One Big Table (OBT, rejected as canonical source)

Flattening split payments + order items + multiple returns multiplies money by fanout. An OBT is acceptable only if all measures are preaggregated/allocated to a documented single grain and testing proves no duplication. For this project, a separate reconciliation view is safer and more transparent.

## Data Vault (not needed Week 3)

Hubs/links/satellites can capture historical source integration and auditability across many independent systems, but the current two-source local demo does not justify operational complexity. Only revisit if P4/P5 shows concrete multi-source, late-arriving, immutable history requirements.
