import hashlib

import pandas as pd

from dataforge.generator import generate


def test_reproducible_fixture_and_business_integrity(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    c1 = generate(count=120, seed=77, dest=first)
    c2 = generate(count=120, seed=77, dest=second)
    assert c1 == c2 and c1["orders"] == 120
    for name in c1:
        assert hashlib.sha256((first / f"{name}.csv").read_bytes()).hexdigest() == \
               hashlib.sha256((second / f"{name}.csv").read_bytes()).hexdigest()
    orders = pd.read_csv(first / "orders.csv")
    items = pd.read_csv(first / "order_items.csv")
    products = pd.read_csv(first / "products.csv")
    customers = pd.read_csv(first / "customers.csv")
    segments = pd.read_csv(first / "customer_segments.csv")
    assert set(items.order_id).issubset(set(orders.order_id))
    assert set(items.product_id).issubset(set(products.product_id))
    assert set(orders.customer_id).issubset(set(customers.customer_id))
    assert len(segments) >= len(customers)
    current = segments[segments.valid_to.isna()]
    assert dict(zip(current.customer_id, current.segment)) == \
           dict(zip(customers.customer_id, customers.segment))
    assert items.quantity.min() > 0
    assert items.discount_pct.between(0, 1).all()


def test_generator_rejects_nonpositive_count(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        generate(count=0, dest=tmp_path)
