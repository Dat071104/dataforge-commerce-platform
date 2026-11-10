"""Explicit cloud types for the current all-string DataForge Bronze Parquet contract."""

from __future__ import annotations

from dataclasses import dataclass

from ..ingestion import contracts as local_contracts


@dataclass(frozen=True)
class FieldContract:
    name: str
    bq_type: str
    nullable: bool = False
    precision: int | None = None
    scale: int | None = None


@dataclass(frozen=True)
class SourceContract:
    fields: tuple[FieldContract, ...]
    primary_key: tuple[str, ...]

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)


def _field(
    name: str,
    bq_type: str,
    *,
    nullable: bool = False,
    precision: int | None = None,
    scale: int | None = None,
) -> FieldContract:
    return FieldContract(name, bq_type, nullable, precision, scale)


SOURCE_CONTRACTS: dict[str, SourceContract] = {
    "geography": SourceContract(
        (_field("province_id", "STRING"), _field("province", "STRING"),
         _field("region", "STRING")),
        ("province_id",),
    ),
    "customers": SourceContract(
        (_field("customer_id", "STRING"), _field("signup_date", "DATE"),
         _field("province_id", "STRING"), _field("segment", "STRING")),
        ("customer_id",),
    ),
    "customer_segments": SourceContract(
        (_field("customer_id", "STRING"), _field("segment", "STRING"),
         _field("valid_from", "DATE"), _field("valid_to", "DATE", nullable=True)),
        ("customer_id", "valid_from"),
    ),
    "products": SourceContract(
        (_field("product_id", "STRING"), _field("category", "STRING"),
         _field("subcategory", "STRING"),
         _field("base_price", "NUMERIC", precision=18, scale=2),
         _field("unit_cogs", "NUMERIC", precision=18, scale=2)),
        ("product_id",),
    ),
    "orders": SourceContract(
        (_field("order_id", "STRING"), _field("customer_id", "STRING"),
         _field("order_date", "DATE"), _field("province_id", "STRING"),
         _field("status", "STRING")),
        ("order_id",),
    ),
    "order_items": SourceContract(
        (_field("order_item_id", "STRING"), _field("order_id", "STRING"),
         _field("product_id", "STRING"), _field("quantity", "INT64"),
         _field("unit_price", "NUMERIC", precision=18, scale=2),
         _field("discount_pct", "NUMERIC", precision=8, scale=4)),
        ("order_item_id",),
    ),
    "payments": SourceContract(
        (_field("payment_id", "STRING"), _field("order_id", "STRING"),
         _field("payment_date", "DATE"),
         _field("amount", "NUMERIC", precision=18, scale=2),
         _field("status", "STRING"), _field("method", "STRING")),
        ("payment_id",),
    ),
    "shipments": SourceContract(
        (_field("shipment_id", "STRING"), _field("order_id", "STRING"),
         _field("ship_date", "DATE"),
         _field("delivery_date", "DATE", nullable=True),
         _field("status", "STRING"), _field("carrier", "STRING")),
        ("shipment_id",),
    ),
    "returns": SourceContract(
        (_field("return_id", "STRING"), _field("order_item_id", "STRING"),
         _field("return_date", "DATE"),
         _field("refund_amount", "NUMERIC", precision=18, scale=2),
         _field("status", "STRING")),
        ("return_id",),
    ),
    "inventory": SourceContract(
        (_field("snapshot_date", "DATE"), _field("product_id", "STRING"),
         _field("quantity_in_stock", "INT64"), _field("reorder_point", "INT64")),
        ("snapshot_date", "product_id"),
    ),
    "weather_daily": SourceContract(
        (_field("province_id", "STRING"), _field("observation_date", "DATE"),
         _field("precipitation_mm", "NUMERIC", nullable=True, precision=12, scale=3),
         _field("temp_max_c", "NUMERIC", nullable=True, precision=8, scale=2),
         _field("source", "STRING")),
        ("province_id", "observation_date"),
    ),
}


def source_contract(source: str) -> SourceContract:
    try:
        spec = SOURCE_CONTRACTS[source]
    except KeyError as exc:
        raise ValueError(f"unsupported cloud source {source!r}") from exc

    local = local_contracts()
    if source not in local or spec.columns != tuple(local[source]["required_columns"]):
        raise ValueError(
            f"cloud type contract for {source!r} does not match configs/sources.csv"
        )
    if spec.primary_key != tuple(local[source]["primary_key"]):
        raise ValueError(
            f"cloud primary key for {source!r} does not match configs/sources.csv"
        )
    return spec
