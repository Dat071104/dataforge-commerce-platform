from decimal import Decimal

from dataforge.generator import generate
from dataforge.reference import reference_metrics


def test_reference_oracle_splits_and_refunds(tmp_path):
    generate(count=250, seed=42, dest=tmp_path)
    actual = reference_metrics(tmp_path)
    assert actual["orders"] == 250
    assert actual["order_items"] >= 250
    assert Decimal(actual["collection_variance_vnd"]) == 0
    assert Decimal(actual["fulfilled_sales_proxy_vnd"]) >= Decimal(actual["completed_refunds_vnd"])
