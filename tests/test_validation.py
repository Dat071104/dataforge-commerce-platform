import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from dataforge.ingestion import DataQualityError, contracts, validate


def _isolated_ingest_dirs(monkeypatch, tmp_path):
    from dataforge import ingestion

    manifests = tmp_path / "manifests"
    monkeypatch.setattr(ingestion, "BRONZE", tmp_path / "bronze")
    monkeypatch.setattr(ingestion, "MANIFESTS", manifests)
    monkeypatch.setattr(ingestion, "QUARANTINE", tmp_path / "quarantine")
    return ingestion, manifests


def _read_active_run(manifests):
    pointer = json.loads((manifests / "active.json").read_text(encoding="utf-8"))
    run = json.loads((manifests / "runs" / f"{pointer['run_id']}.json")
                     .read_text(encoding="utf-8"))
    return pointer, run


def test_contracts_have_unique_source_names():
    assert len(contracts()) == 11
    assert "order_items" in contracts()


def test_detects_duplicate_ids(monkeypatch, tmp_path):
    from dataforge import ingestion
    monkeypatch.setattr(ingestion, "QUARANTINE", tmp_path)
    df = pd.DataFrame({"province_id": ["HCM", "HCM"], "province": ["Saigon", "Saigon"],
                       "region": ["South", "South"]})
    with pytest.raises(DataQualityError, match="2 invalid rows"):
        validate(df, "geography")
    assert (tmp_path / "geography_rejected.csv").exists()


def test_detects_invalid_discount(monkeypatch, tmp_path):
    from dataforge import ingestion
    monkeypatch.setattr(ingestion, "QUARANTINE", tmp_path)
    df = pd.DataFrame({
        "order_item_id": ["1"], "order_id": ["o"], "product_id": ["p"],
        "quantity": [2], "unit_price": [100], "discount_pct": [1.5]
    })
    with pytest.raises(DataQualityError, match="invalid"):
        validate(df, "order_items")


def test_rejects_missing_columns():
    with pytest.raises(DataQualityError, match="missing required"):
        validate(pd.DataFrame({"order_id": ["1"]}), "orders")


def test_rejects_unexpected_columns_as_schema_drift():
    df = pd.DataFrame({"province_id": ["HCM"], "province": ["Ho Chi Minh"],
                       "region": ["South"], "new_field": ["unexpected"]})
    with pytest.raises(DataQualityError, match="schema drift"):
        validate(df, "geography")


def test_rejects_blank_non_key_text_fields(monkeypatch, tmp_path):
    from dataforge import ingestion
    monkeypatch.setattr(ingestion, "QUARANTINE", tmp_path)
    df = pd.DataFrame({"order_id": ["O1"], "customer_id": ["C1"],
                       "order_date": ["2022-01-01"], "province_id": ["HCM"], "status": [" "]})
    with pytest.raises(DataQualityError, match="1 invalid rows"):
        validate(df, "orders")
    assert "empty_value:status" in (tmp_path / "orders_rejected.csv").read_text()


def test_rejects_invalid_optional_date_and_interval(monkeypatch, tmp_path):
    from dataforge import ingestion
    monkeypatch.setattr(ingestion, "QUARANTINE", tmp_path)
    shipments = pd.DataFrame({"shipment_id": ["S1"], "order_id": ["O1"],
                              "ship_date": ["2022-01-02"], "delivery_date": ["2022-02-31"],
                              "status": ["delivered"], "carrier": ["GHN"]})
    with pytest.raises(DataQualityError, match="1 invalid rows"):
        validate(shipments, "shipments")
    assert "invalid_date:delivery_date" in (tmp_path / "shipments_rejected.csv").read_text()

    segments = pd.DataFrame({"customer_id": ["C1"], "segment": ["Regular"],
                             "valid_from": ["2022-02-15"], "valid_to": ["2022-02-14"]})
    with pytest.raises(DataQualityError, match="1 invalid rows"):
        validate(segments, "customer_segments")
    assert "invalid_interval:valid_to" in (tmp_path / "customer_segments_rejected.csv").read_text()


def test_rejects_unparseable_optional_weather_numeric(monkeypatch, tmp_path):
    from dataforge import ingestion
    monkeypatch.setattr(ingestion, "QUARANTINE", tmp_path)
    df = pd.DataFrame({"province_id": ["HCM"], "observation_date": ["2022-01-01"],
                       "precipitation_mm": [""], "temp_max_c": ["not-a-number"],
                       "source": ["synthetic"]})
    with pytest.raises(DataQualityError, match="1 invalid rows"):
        validate(df, "weather_daily")


@pytest.mark.parametrize(("source", "row"), [
    ("products", {"product_id": "P1", "category": "Fashion", "subcategory": "Line 1",
                  "base_price": "100.00", "unit_cogs": "-1"}),
    ("order_items", {"order_item_id": "I1", "order_id": "O1", "product_id": "P1",
                      "quantity": "1.5", "unit_price": "100", "discount_pct": "0.1"}),
    ("payments", {"payment_id": "PAY1", "order_id": "O1", "payment_date": "2022-01-01",
                  "amount": "not-a-decimal", "status": "success", "method": "card"}),
    ("payments", {"payment_id": "PAY1", "order_id": "O1", "payment_date": "2022-01-01",
                  "amount": "10.001", "status": "success", "method": "card"}),
    ("payments", {"payment_id": "PAY1", "order_id": "O1", "payment_date": "2022-01-01",
                  "amount": "10000000000000000", "status": "success", "method": "card"}),
    ("returns", {"return_id": "R1", "order_item_id": "I1", "return_date": "2022-01-01",
                 "refund_amount": "-0.01", "status": "completed"}),
    ("inventory", {"snapshot_date": "2022-01-01", "product_id": "P1",
                   "quantity_in_stock": "2.5", "reorder_point": "1"}),
    ("inventory", {"snapshot_date": "2022-01-01", "product_id": "P1",
                   "quantity_in_stock": "2147483648", "reorder_point": "1"}),
])
def test_rejects_bad_numeric_columns(monkeypatch, tmp_path, source, row):
    from dataforge import ingestion
    monkeypatch.setattr(ingestion, "QUARANTINE", tmp_path)
    with pytest.raises(DataQualityError, match="1 invalid rows"):
        validate(pd.DataFrame([row]), source)


def test_valid_optional_fields_and_clears_stale_quarantine(monkeypatch, tmp_path):
    from dataforge import ingestion

    monkeypatch.setattr(ingestion, "QUARANTINE", tmp_path)
    stale = tmp_path / "shipments_rejected.csv"
    stale.write_text("reject_reason,shipment_id\nold failure,S0\n", encoding="utf-8")
    df = pd.DataFrame({"shipment_id": ["S1"], "order_id": ["O1"],
                       "ship_date": ["2022-01-02"], "delivery_date": [""],
                       "status": ["pending"], "carrier": ["GHN"]})
    assert validate(df, "shipments").equals(df)
    assert not stale.exists()


def test_ingest_reuses_content_addressed_parquet_on_repeat(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=7, dest=source)

    first = ingestion.ingest(source, ["geography"])["geography"]
    parquet = Path(first["bronze_file"])
    before = hashlib.sha256(parquet.read_bytes()).hexdigest()
    second = ingestion.ingest(source, ["geography"])["geography"]

    assert second["source_sha256"] == first["source_sha256"]
    assert second["bronze_file"] == first["bronze_file"]
    assert hashlib.sha256(parquet.read_bytes()).hexdigest() == before
    assert len(list((tmp_path / "bronze" / "geography").glob("sha256=*/*.parquet"))) == 1
    pointer, run = _read_active_run(manifests)
    assert run["run_id"] == pointer["run_id"]
    assert run["status"] == "complete"
    assert run["sources"]["geography"]["source_sha256"] == first["source_sha256"]


def test_ingest_all_sources_creates_verifiable_bronze_snapshot_set(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=120, seed=22, dest=source)
    results = ingestion.ingest(source)
    pointer, run = _read_active_run(manifests)

    assert set(results) == set(contracts())
    assert run["run_id"] == pointer["run_id"]
    assert run["status"] == "complete"
    assert set(run["sources"]) == set(contracts())
    for name, metadata in results.items():
        source_hash = hashlib.sha256((source / f"{name}.csv").read_bytes()).hexdigest()
        parquet = Path(metadata["bronze_file"])
        assert metadata["source_sha256"] == source_hash
        assert run["sources"][name] == metadata
        assert metadata["data_classification"] == "synthetic"
        assert parquet.is_file()
        assert len(pd.read_parquet(parquet)) == metadata["rows_accepted"]
        assert json.loads((manifests / f"{name}.json").read_text(encoding="utf-8")) == metadata


def test_first_ingest_atomically_publishes_complete_active_run(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=12, dest=source)
    result = ingestion.ingest(source, ["geography", "orders"])

    pointer, run = _read_active_run(manifests)
    assert set(pointer) == {"run_id"}
    assert run["status"] == "complete"
    assert run["sources_requested"] == ["geography", "orders"]
    assert set(run["sources"]) == {"geography", "orders"}
    assert run["sources"]["orders"]["source_sha256"] == result["orders"]["source_sha256"]
    assert json.loads((manifests / "orders.json").read_text(encoding="utf-8")) == \
        run["sources"]["orders"]


def test_subset_ingest_merges_prior_active_sources(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=13, dest=source)
    ingestion.ingest(source, ["geography"])
    _, first_run = _read_active_run(manifests)
    prior_geography = first_run["sources"]["geography"]

    ingestion.ingest(source, ["orders"])
    pointer, second_run = _read_active_run(manifests)
    assert pointer["run_id"] != first_run["run_id"]
    assert second_run["previous_run_id"] == first_run["run_id"]
    assert set(second_run["sources"]) == {"geography", "orders"}
    assert second_run["sources"]["geography"] == prior_geography
    assert second_run["sources"]["orders"]["source"] == "orders"


def test_subset_snapshot_idempotency_and_changed_source_hash(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=18, dest=source)
    ingestion.ingest(source, ["geography", "orders"])
    _, initial_run = _read_active_run(manifests)
    initial_geography = initial_run["sources"]["geography"]
    initial_orders = initial_run["sources"]["orders"]
    initial_geography_sha = hashlib.sha256((source / "geography.csv").read_bytes()).hexdigest()
    initial_orders_sha = hashlib.sha256((source / "orders.csv").read_bytes()).hexdigest()
    assert initial_geography["source_sha256"] == initial_geography_sha
    assert initial_orders["source_sha256"] == initial_orders_sha
    initial_mirror_orders = (manifests / "orders.json").read_bytes()
    geography_parquet = Path(initial_geography["bronze_file"])
    initial_parquet_hash = hashlib.sha256(geography_parquet.read_bytes()).hexdigest()

    # An unchanged subset replay creates no new bronze snapshot and retains orders.
    repeated = ingestion.ingest(source, ["geography"])
    _, repeated_run = _read_active_run(manifests)
    repeated_geography = repeated_run["sources"]["geography"]
    assert repeated["geography"]["source_sha256"] == initial_geography["source_sha256"]
    assert repeated_geography["bronze_file"] == initial_geography["bronze_file"]
    assert hashlib.sha256(geography_parquet.read_bytes()).hexdigest() == initial_parquet_hash
    assert repeated_run["sources"]["orders"] == initial_orders
    assert (manifests / "orders.json").read_bytes() == initial_mirror_orders

    # A valid source edit creates a distinct hash-addressed snapshot and becomes latest.
    geography_csv = source / "geography.csv"
    geography_df = pd.read_csv(geography_csv, dtype="string")
    geography_df.loc[0, "province"] = "Updated synthetic province"
    geography_df.to_csv(geography_csv, index=False)
    changed_sha = hashlib.sha256(geography_csv.read_bytes()).hexdigest()
    changed = ingestion.ingest(source, ["geography"])
    _, changed_run = _read_active_run(manifests)
    changed_geography = changed_run["sources"]["geography"]

    assert changed["geography"]["source_sha256"] == changed_sha
    assert changed_geography["source_sha256"] == changed_sha
    assert changed_geography["bronze_file"] != initial_geography["bronze_file"]
    assert Path(changed_geography["bronze_file"]).is_file()
    assert Path(initial_geography["bronze_file"]).is_file()
    assert changed_run["sources"]["orders"] == initial_orders
    assert (manifests / "orders.json").read_bytes() == initial_mirror_orders
    assert json.loads((manifests / "geography.json").read_text(encoding="utf-8")) == \
        changed_geography
    assert len(list((tmp_path / "bronze" / "geography").glob("sha256=*/*.parquet"))) == 2


def test_first_active_run_migrates_legacy_source_manifests(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=17, dest=source)
    geography = ingestion.ingest(source, ["geography"])["geography"]
    (manifests / "active.json").unlink()

    ingestion.ingest(source, ["orders"])
    _, run = _read_active_run(manifests)
    assert run["previous_run_id"] is None
    assert set(run["sources"]) == {"geography", "orders"}
    assert run["sources"]["geography"] == geography


def test_invalid_later_source_keeps_prior_active_snapshot(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=14, dest=source)
    ingestion.ingest(source, ["geography", "orders"])
    active_before = (manifests / "active.json").read_bytes()
    _, prior_run = _read_active_run(manifests)

    geography = pd.read_csv(source / "geography.csv", dtype="string")
    geography.loc[0, "province"] = "Changed province"
    geography.to_csv(source / "geography.csv", index=False)
    orders = pd.read_csv(source / "orders.csv", dtype="string")
    orders.loc[0, "status"] = ""
    orders.to_csv(source / "orders.csv", index=False)

    with pytest.raises(DataQualityError, match="invalid rows"):
        ingestion.ingest(source, ["geography", "orders"])

    assert (manifests / "active.json").read_bytes() == active_before
    _, still_active = _read_active_run(manifests)
    assert still_active["run_id"] == prior_run["run_id"]
    assert still_active["sources"] == prior_run["sources"]
    failed_runs = [json.loads(path.read_text(encoding="utf-8"))
                   for path in (manifests / "runs").glob("*.json")]
    failed = next(run for run in failed_runs if run["status"] == "failed")
    assert failed["failed_source"] == "orders"
    assert failed["prepared_sources"] == ["geography"]
    assert json.loads((manifests / "geography.json").read_text(encoding="utf-8")) == \
        prior_run["sources"]["geography"]


def test_parquet_write_failure_keeps_prior_active_snapshot(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=15, dest=source)
    ingestion.ingest(source, ["geography"])
    active_before = (manifests / "active.json").read_bytes()
    geography = pd.read_csv(source / "geography.csv", dtype="string")
    geography.loc[0, "province"] = "Changed province"
    geography.to_csv(source / "geography.csv", index=False)

    def fail_write(self, *args, **kwargs):
        raise OSError("simulated Parquet write failure")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", fail_write)
    with pytest.raises(OSError, match="simulated Parquet write failure"):
        ingestion.ingest(source, ["geography"])

    assert (manifests / "active.json").read_bytes() == active_before
    failed_runs = [json.loads(path.read_text(encoding="utf-8"))
                   for path in (manifests / "runs").glob("*.json")]
    failed = next(run for run in failed_runs if run["status"] == "failed")
    assert failed["failed_source"] == "geography"
    assert list((tmp_path / "bronze" / "geography").glob("sha256=*/*.tmp.parquet")) == []


def test_active_pointer_replace_failure_keeps_prior_active_snapshot(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=16, dest=source)
    ingestion.ingest(source, ["geography"])
    active_before = (manifests / "active.json").read_bytes()
    geography = pd.read_csv(source / "geography.csv", dtype="string")
    geography.loc[0, "province"] = "Changed province"
    geography.to_csv(source / "geography.csv", index=False)

    real_replace = ingestion.os.replace
    active_path = manifests / "active.json"

    def fail_active_replace(source_path, destination_path):
        if Path(destination_path) == active_path:
            raise OSError("simulated active pointer replace failure")
        return real_replace(source_path, destination_path)

    monkeypatch.setattr(ingestion.os, "replace", fail_active_replace)
    with pytest.raises(OSError, match="active pointer replace failure"):
        ingestion.ingest(source, ["geography"])

    assert active_path.read_bytes() == active_before
    failed_runs = [json.loads(path.read_text(encoding="utf-8"))
                   for path in (manifests / "runs").glob("*.json")]
    failed = next(run for run in failed_runs if run["status"] == "failed")
    assert failed["failed_source"] == "geography"


def test_malformed_csv_records_failed_run_without_changing_active(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=19, dest=source)
    ingestion.ingest(source, ["geography"])
    active_before = (manifests / "active.json").read_bytes()

    (source / "products.csv").write_text(
        'product_id,category,subcategory,base_price,unit_cogs\n"P1,Fashion,Line 1,100,50\n',
        encoding="utf-8",
    )
    with pytest.raises(pd.errors.ParserError):
        ingestion.ingest(source, ["products"])

    assert (manifests / "active.json").read_bytes() == active_before
    failed = [json.loads(path.read_text(encoding="utf-8"))
              for path in (manifests / "runs").glob("*.json")
              if json.loads(path.read_text(encoding="utf-8")).get("status") == "failed"]
    assert len(failed) == 1
    assert failed[0]["failed_source"] == "products"
    assert "ParserError" in failed[0]["error"]


def test_malformed_provenance_json_records_failed_run_without_changing_active(
        monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=20, dest=source)
    ingestion.ingest(source, ["geography"])
    active_before = (manifests / "active.json").read_bytes()
    (source / "_DATAFORGE_SOURCE.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        ingestion.ingest(source, ["orders"])

    assert (manifests / "active.json").read_bytes() == active_before
    failed = [json.loads(path.read_text(encoding="utf-8"))
              for path in (manifests / "runs").glob("*.json")
              if json.loads(path.read_text(encoding="utf-8")).get("status") == "failed"]
    assert len(failed) == 1
    assert failed[0]["failed_source"] is None
    assert "JSONDecodeError" in failed[0]["error"]


def test_ingest_preserves_source_provenance_tags_on_subset_update(monkeypatch, tmp_path):
    ingestion, manifests = _isolated_ingest_dirs(monkeypatch, tmp_path)
    from dataforge.generator import generate

    source = tmp_path / "source"
    generate(count=3, seed=21, dest=source)
    ingestion.ingest(source, ["geography", "orders"])
    _, initial_run = _read_active_run(manifests)
    assert initial_run["sources"]["geography"]["data_classification"] == "synthetic"
    assert initial_run["sources"]["orders"]["data_classification"] == "synthetic"

    geography = pd.read_csv(source / "geography.csv", dtype="string")
    geography.loc[0, "province"] = "Changed without provenance update"
    geography.to_csv(source / "geography.csv", index=False)
    ingestion.ingest(source, ["geography"])
    _, updated_run = _read_active_run(manifests)

    assert updated_run["sources"]["geography"]["data_classification"] == \
        "unverified_modified_source"
    assert updated_run["sources"]["orders"]["data_classification"] == "synthetic"


def test_duplicate_order_item_key_is_quarantined(monkeypatch, tmp_path):
    from dataforge import ingestion

    monkeypatch.setattr(ingestion, "QUARANTINE", tmp_path)
    df = pd.DataFrame({"order_item_id": ["I1", "I1"], "order_id": ["O1", "O1"],
                       "product_id": ["P1", "P1"], "quantity": [1, 1],
                       "unit_price": [100, 100], "discount_pct": [0, 0]})
    with pytest.raises(DataQualityError, match="2 invalid rows"):
        validate(df, "order_items")
    rejected = pd.read_csv(tmp_path / "order_items_rejected.csv")
    assert len(rejected) == 2
    assert rejected.reject_reason.str.contains("duplicate_key").all()


def test_rejects_null_primary_key(monkeypatch, tmp_path):
    from dataforge import ingestion
    monkeypatch.setattr(ingestion, "QUARANTINE", tmp_path)
    df = pd.DataFrame({"province_id": [""], "province": ["Ho Chi Minh"],
                       "region": ["South"]})
    with pytest.raises(DataQualityError, match="1 invalid rows"):
        validate(df, "geography")
