"""Deterministic, explicitly synthetic Vietnamese e-commerce source fixtures."""
from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .settings import SOURCE

PROVINCES = [
    ("HCM", "TP. Ho Chi Minh", "South"),
    ("HN", "Ha Noi", "North"),
    ("DN", "Da Nang", "Central"),
    ("CT", "Can Tho", "South"),
    ("HP", "Hai Phong", "North"),
    ("BD", "Binh Duong", "South"),
    ("KH", "Khanh Hoa", "Central"),
    ("LA", "Long An", "South"),
]
START = date(2022, 1, 1)
END = date(2022, 3, 31)


def _write(path: Path, columns: list[str], rows: list[tuple]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(columns)
        writer.writerows(rows)


def generate(count: int = 3000, seed: int = 42, dest: Path = SOURCE) -> dict[str, int]:
    """Generate reproducible fixtures. Never represent this as a real retailer's data."""
    if count < 1:
        raise ValueError("count must be positive")
    rng = random.Random(seed)
    dest.mkdir(parents=True, exist_ok=True)
    marker = dest / "_DATAFORGE_SOURCE.json"
    existing_csvs = list(dest.glob("*.csv"))
    if existing_csvs and not marker.exists():
        raise FileExistsError(
            f"{dest} has CSVs without synthetic provenance marker; refusing overwrite"
        )
    if marker.exists():
        try:
            provenance = json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"invalid provenance marker in {dest}; refusing overwrite") from exc
        if not isinstance(provenance, dict) or provenance.get("dataset_class") != "synthetic":
            raise FileExistsError(
                f"{dest} is not an explicitly synthetic fixture; refusing overwrite"
            )
        overrides = provenance.get("source_overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError(f"invalid source overrides in {dest}; refusing overwrite")
        if any(label != "synthetic" for label in overrides.values()):
            raise FileExistsError(
                f"{dest} includes externally sourced data; refusing overwrite"
            )
        recorded_hashes = provenance.get("file_sha256", {})
        if not isinstance(recorded_hashes, dict):
            raise ValueError(f"invalid synthetic source hashes in {dest}; refusing overwrite")
        for csv_path in existing_csvs:
            recorded = recorded_hashes.get(csv_path.stem)
            current = hashlib.sha256(csv_path.read_bytes()).hexdigest()
            if recorded != current:
                raise FileExistsError(
                    f"{csv_path} is not the recorded synthetic fixture; refusing overwrite"
                )
    data: dict[str, tuple[list[str], list[tuple]]] = {}

    data["geography"] = (["province_id", "province", "region"], PROVINCES)
    customers = []
    segments = []
    for i in range(1, 301):
        cid = f"C{i:05d}"
        province = rng.choice(PROVINCES)[0]
        original = rng.choice(["Regular", "Regular", "VIP"])
        if i % 7 == 0:
            new_segment = "VIP" if original == "Regular" else "Regular"
            segments.append((cid, original, "2021-01-01", "2022-02-15"))
            segments.append((cid, new_segment, "2022-02-15", ""))
            customers.append((cid, "2021-01-01", province, new_segment))
        else:
            segments.append((cid, original, "2021-01-01", ""))
            customers.append((cid, "2021-01-01", province, original))
    data["customers"] = (["customer_id", "signup_date", "province_id", "segment"], customers)
    data["customer_segments"] = (
        ["customer_id", "segment", "valid_from", "valid_to"], segments
    )

    products = []
    for i in range(1, 61):
        cat = rng.choice(["Fashion", "Footwear", "Accessories", "Beauty"])
        price = rng.randrange(100_000, 1_200_001, 10_000)
        cost = round(price * rng.choice([0.45, 0.55, 0.65]))
        products.append((f"P{i:04d}", cat, f"{cat} / Line {i % 5 + 1}", price, cost))
    data["products"] = (
        ["product_id", "category", "subcategory", "base_price", "unit_cogs"], products
    )

    orders = []
    items = []
    payments = []
    shipments = []
    returns = []
    units_by_product = defaultdict(int)
    order_dates = (END - START).days + 1
    for i in range(1, count + 1):
        oid = f"O{i:07d}"
        customer = rng.choice(customers)
        day = START + timedelta(days=rng.randrange(order_dates))
        province = customer[2]
        status = rng.choices(["delivered", "cancelled", "processing"], [0.86, 0.07, 0.07])[0]
        orders.append((oid, customer[0], day.isoformat(), province, status))
        total = 0
        item_ids = []
        for j in range(rng.randint(1, 3)):
            product = rng.choice(products)
            qty = rng.choice([1, 1, 1, 2, 3])
            discount_pct = rng.choice([0, 0, 0, 0.05, 0.10, 0.20])
            amount = round(qty * product[3] * (1 - discount_pct))
            total += amount
            iid = f"I{i:07d}-{j+1}"
            item_ids.append((iid, amount))
            items.append((iid, oid, product[0], qty, product[3], f"{discount_pct:.2f}"))
            if status == "delivered":
                units_by_product[product[0]] += qty
        if status == "delivered":
            pay_day = day + timedelta(days=rng.randint(0, 2))
            if i % 11 == 0:
                split = round(total * 0.40)
                payments.append((f"PAY{i:07d}-1", oid, pay_day.isoformat(), split,
                                 "success", "wallet"))
                payments.append((f"PAY{i:07d}-2", oid, pay_day.isoformat(), total - split,
                                 "success", "card"))
            else:
                payments.append((f"PAY{i:07d}-1", oid, pay_day.isoformat(), total,
                                 "success", rng.choice(["card", "COD", "wallet"])))
            ship_date = day + timedelta(days=rng.randint(0, 2))
            transit = rng.randint(1, 7)
            shipments.append((f"S{i:07d}", oid, ship_date.isoformat(),
                              (ship_date + timedelta(days=transit)).isoformat(),
                              "delivered", rng.choice(["GHN", "GHTK", "Viettel Post"])))
            if i % 19 == 0:
                iid, item_amount = rng.choice(item_ids)
                returns.append((f"R{i:07d}", iid, (ship_date + timedelta(days=transit + 3)).isoformat(),
                                item_amount, "completed"))
        elif status == "cancelled" and i % 3 == 0:
            payments.append((f"PAY{i:07d}-1", oid, day.isoformat(), total,
                             "failed", "card"))

    data["orders"] = (["order_id", "customer_id", "order_date", "province_id", "status"], orders)
    data["order_items"] = (
        ["order_item_id", "order_id", "product_id", "quantity", "unit_price", "discount_pct"],
        items,
    )
    data["payments"] = (
        ["payment_id", "order_id", "payment_date", "amount", "status", "method"],
        payments,
    )
    data["shipments"] = (
        ["shipment_id", "order_id", "ship_date", "delivery_date", "status", "carrier"],
        shipments,
    )
    data["returns"] = (
        ["return_id", "order_item_id", "return_date", "refund_amount", "status"],
        returns,
    )

    inventory = []
    for month in (date(2022, 1, 1), date(2022, 2, 1), date(2022, 3, 1)):
        for p in products:
            inventory.append((month.isoformat(), p[0], rng.randint(20, 400), 25))
    data["inventory"] = (
        ["snapshot_date", "product_id", "quantity_in_stock", "reorder_point"], inventory
    )
    weather = []
    for prov in PROVINCES:
        for offset in range(order_dates + 10):
            day = START + timedelta(days=offset)
            rainfall = rng.choice([0, 0, 0, 0, 0, 1, 2, 5, 10, 25])
            weather.append((prov[0], day.isoformat(), rainfall,
                            rng.randint(27, 38), "synthetic"))
    data["weather_daily"] = (
        ["province_id", "observation_date", "precipitation_mm", "temp_max_c", "source"],
        weather,
    )

    summary = {}
    file_hashes = {}
    for name, (cols, rows) in data.items():
        csv_path = dest / f"{name}.csv"
        _write(csv_path, cols, rows)
        summary[name] = len(rows)
        file_hashes[name] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    marker.write_text(json.dumps({"dataset_class": "synthetic", "seed": seed,
                                  "order_count": count, "file_sha256": file_hashes,
                                  "source_overrides": {}}, indent=2), encoding="utf-8")
    return summary
