"""Independent CSV/Decimal reference oracle for the generated synthetic dataset."""
from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from .settings import SOURCE


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def reference_metrics(source_dir: Path = SOURCE) -> dict[str, int | str]:
    """Metric control without SQL, Pandas, Parquet or psycopg dependencies."""
    orders = {x["order_id"]: x for x in _rows(source_dir / "orders.csv")}
    products = {x["product_id"]: x for x in _rows(source_dir / "products.csv")}
    items = _rows(source_dir / "order_items.csv")
    payments = _rows(source_dir / "payments.csv")
    returns = _rows(source_dir / "returns.csv")
    item_net: dict[str, Decimal] = {}
    fulfilled_sales = Decimal(0)
    fulfilled_cogs = Decimal(0)
    for i in items:
        qty = Decimal(i["quantity"])
        net = qty * Decimal(i["unit_price"]) * (Decimal(1) - Decimal(i["discount_pct"]))
        item_net[i["order_item_id"]] = net
        if orders[i["order_id"]]["status"] == "delivered":
            fulfilled_sales += net
            fulfilled_cogs += qty * Decimal(products[i["product_id"]]["unit_cogs"])
    collected = sum((Decimal(p["amount"]) for p in payments if p["status"] == "success"),
                    Decimal(0))
    refunded = sum((Decimal(r["refund_amount"]) for r in returns if r["status"] == "completed"),
                   Decimal(0))
    for r in returns:
        if Decimal(r["refund_amount"]) > item_net[r["order_item_id"]]:
            raise ValueError(f"refund exceeds line value: {r['return_id']}")
    return {
        "orders": len(orders), "order_items": len(items), "payment_events": len(payments),
        "delivered_orders": sum(o["status"] == "delivered" for o in orders.values()),
        "fulfilled_sales_proxy_vnd": str(fulfilled_sales),
        "fulfilled_cogs_proxy_vnd": str(fulfilled_cogs),
        "collected_vnd": str(collected),
        "completed_refunds_vnd": str(refunded),
        "collection_variance_vnd": str(collected - fulfilled_sales),
    }
