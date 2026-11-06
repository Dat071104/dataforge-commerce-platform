"""Fail-closed CSV validation and immutable Parquet bronze snapshots."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

import pandas as pd

from .settings import BRONZE, MANIFESTS, QUARANTINE, ROOT, SOURCE


class DataQualityError(ValueError):
    pass


logger = logging.getLogger(__name__)


def contracts() -> dict[str, dict[str, list[str]]]:
    path = ROOT / "configs" / "sources.csv"
    with path.open(encoding="utf-8", newline="") as f:
        return {row["source"]: {
            "primary_key": row["primary_key"].split("|"),
            "required_columns": row["required_columns"].split("|"),
        } for row in csv.DictReader(f)}


def validate(df: pd.DataFrame, source: str) -> pd.DataFrame:
    specs = contracts()
    if source not in specs:
        raise DataQualityError(f"unknown source {source!r}; valid: {list(specs)}")
    required = specs[source]["required_columns"]
    absent = [col for col in required if col not in df.columns]
    if absent:
        raise DataQualityError(f"{source}: missing required columns: {absent}")
    unexpected = [col for col in df.columns if col not in required]
    if unexpected:
        raise DataQualityError(f"{source}: unexpected columns (schema drift): {unexpected}")
    if df.empty:
        raise DataQualityError(f"{source}: empty dataset")
    errors = pd.Series("", index=df.index, dtype="object")

    def add(mask: pd.Series, message: str) -> None:
        nonlocal errors
        errors.loc[mask] += f"{message};"

    for field in specs[source]["primary_key"]:
        add(df[field].isna() | df[field].astype(str).str.strip().eq(""), f"null_key:{field}")
    add(df.duplicated(subset=specs[source]["primary_key"], keep=False), "duplicate_key")
    date_columns = {
        "customers": ["signup_date"], "customer_segments": ["valid_from"],
        "orders": ["order_date"], "payments": ["payment_date"],
        "shipments": ["ship_date"], "returns": ["return_date"],
        "inventory": ["snapshot_date"], "weather_daily": ["observation_date"],
    }
    optional_dates = {
        "customer_segments": ["valid_to"], "shipments": ["delivery_date"],
    }
    required_numeric = {
        "products": ["base_price", "unit_cogs"],
        "order_items": ["quantity", "unit_price", "discount_pct"],
        "payments": ["amount"],
        "returns": ["refund_amount"],
        "inventory": ["quantity_in_stock", "reorder_point"],
    }
    optional_numeric = {"weather_daily": ["precipitation_mm", "temp_max_c"]}
    integer_numeric = {
        "order_items": ["quantity"],
        "inventory": ["quantity_in_stock", "reorder_point"],
    }
    nonnegative_numeric = {
        "products": ["base_price", "unit_cogs"],
        "order_items": ["quantity", "unit_price"],
        "payments": ["amount"],
        "returns": ["refund_amount"],
        "inventory": ["quantity_in_stock", "reorder_point"],
        "weather_daily": ["precipitation_mm"],
    }
    decimal_specs = {
        "products": {"base_price": (2, 16), "unit_cogs": (2, 16)},
        "order_items": {"unit_price": (2, 16), "discount_pct": (4, 4)},
        "payments": {"amount": (2, 16)},
        "returns": {"refund_amount": (2, 16)},
        "weather_daily": {"precipitation_mm": (3, 9), "temp_max_c": (2, 6)},
    }

    nullable = set(optional_dates.get(source, [])) | set(optional_numeric.get(source, []))
    numeric_fields = required_numeric.get(source, []) + optional_numeric.get(source, [])
    typed_fields = set(date_columns.get(source, [])) | set(optional_dates.get(source, [])) | set(numeric_fields)
    for field in required:
        if field in typed_fields:
            continue
        value = df[field].astype("string")
        add(value.isna() | value.str.strip().eq(""), f"empty_value:{field}")

    for field in date_columns.get(source, []) + optional_dates.get(source, []):
        text = df[field].astype("string").str.strip()
        blank = text.isna() | text.eq("")
        parsed = pd.to_datetime(text.mask(blank), format="%Y-%m-%d", errors="coerce")
        add((parsed.isna() & ~blank) | (parsed.isna() & (field not in nullable)),
            f"invalid_date:{field}")

    for field in numeric_fields:
        text = df[field].astype("string").str.strip()
        blank = text.isna() | text.eq("")
        values = pd.to_numeric(text.mask(blank), errors="coerce")
        invalid = (values.isna() & ~blank) | (values.isna() & (field not in nullable))
        finite = values.map(lambda value: pd.isna(value) or math.isfinite(float(value)))
        invalid |= ~finite
        if field in nonnegative_numeric.get(source, []):
            invalid |= values.lt(0)
        if field in integer_numeric.get(source, []):
            invalid |= values.mod(1).ne(0) | values.gt(2_147_483_647)
        if source == "order_items" and field == "discount_pct":
            invalid |= values.lt(0) | values.gt(1)
        decimal_spec = decimal_specs.get(source, {}).get(field)
        if decimal_spec is not None:
            scale, integral_digits = decimal_spec
            invalid |= text.map(
                lambda value: _violates_decimal_spec(value, scale, integral_digits)
            )
        add(invalid.fillna(False), f"invalid_numeric:{field}")

    if source == "order_items":
        qty = pd.to_numeric(df["quantity"], errors="coerce")
        add(qty.isna() | (qty <= 0), "invalid_quantity")
    if source == "customer_segments":
        start = pd.to_datetime(df["valid_from"], format="%Y-%m-%d", errors="coerce")
        end = pd.to_datetime(df["valid_to"].replace("", pd.NA), format="%Y-%m-%d", errors="coerce")
        add(end.notna() & start.notna() & end.le(start), "invalid_interval:valid_to")
    if source == "shipments":
        ship = pd.to_datetime(df["ship_date"], format="%Y-%m-%d", errors="coerce")
        delivery = pd.to_datetime(df["delivery_date"].replace("", pd.NA),
                                  format="%Y-%m-%d", errors="coerce")
        add(delivery.notna() & ship.notna() & delivery.lt(ship), "invalid_interval:delivery_date")
    bad = errors.ne("")
    if bad.any():
        QUARANTINE.mkdir(parents=True, exist_ok=True)
        rejected = df.loc[bad].copy()
        rejected.insert(0, "reject_reason", errors[bad].values)
        rejected.to_csv(QUARANTINE / f"{source}_rejected.csv", index=False)
        raise DataQualityError(f"{source}: {int(bad.sum())} invalid rows; see data/quarantine/{source}_rejected.csv")
    # A previous failed attempt may have left a quarantine file. Remove it only
    # after this source has passed validation, so the directory reflects the
    # latest validation outcome rather than stale failures.
    (QUARANTINE / f"{source}_rejected.csv").unlink(missing_ok=True)
    return df


def _violates_decimal_spec(value: object, places: int, integral_digits: int) -> bool:
    """Reject values PostgreSQL would round or reject at its declared NUMERIC precision."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return False  # The ordinary numeric parser reports malformed values.
    if not number.is_finite():
        return False  # The ordinary numeric parser reports infinities/NaN.
    normalized = number.normalize()
    scale = max(0, -normalized.as_tuple().exponent)
    digits_before_decimal = normalized.adjusted() + 1 if number else 1
    return scale > places or digits_before_decimal > integral_digits


def _write_json_atomically(path: Path, value: dict) -> None:
    """Replace one JSON file atomically using a temporary file on the same volume."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_parquet_atomically(path: Path, payload: bytes, run_id: str) -> None:
    """Publish immutable Parquet bytes by same-directory atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.stem}.{run_id}.tmp{path.suffix}")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_verified_bronze(
    path: str | Path,
    *,
    source: str,
    expected_sha256: str,
    expected_columns: list[str],
    expected_rows: int,
) -> pd.DataFrame:
    """Read one Parquet snapshot only after hashing the exact bytes parsed."""
    artifact_path = Path(path)
    try:
        payload = artifact_path.read_bytes()
    except OSError as exc:
        raise DataQualityError(f"cannot read bronze Parquet for {source}: {artifact_path}") from exc
    actual_sha256 = hashlib.sha256(payload).hexdigest()
    if actual_sha256 != expected_sha256:
        raise DataQualityError(
            f"bronze SHA-256 mismatch for {source}: expected {expected_sha256}, "
            f"found {actual_sha256} at {artifact_path}"
        )
    try:
        df = pd.read_parquet(io.BytesIO(payload), engine="pyarrow")
    except Exception as exc:
        raise DataQualityError(f"invalid bronze Parquet for {source}: {artifact_path}: {exc}") from exc
    if list(df.columns) != expected_columns:
        raise DataQualityError(
            f"bronze schema mismatch for {source}: expected {expected_columns}, "
            f"got {list(df.columns)}"
        )
    if df.empty:
        raise DataQualityError(f"bronze snapshot for {source} is empty")
    if len(df) != expected_rows:
        raise DataQualityError(
            f"bronze row count mismatch for {source}: expected {expected_rows}, got {len(df)}"
        )
    return df


def _validate_weather_provenance(
    source_dir: Path,
    source_marker: dict,
    source_sha256: str,
    row_count: int,
) -> None:
    """Fail closed when an Open-Meteo CSV and its provenance sidecar disagree."""
    overrides = source_marker.get("source_overrides", {})
    override = overrides.get("weather_daily") if isinstance(overrides, dict) else None
    if not isinstance(override, str) or not override.casefold().startswith("open_meteo"):
        return

    from .weather import PROVENANCE_DIR

    marker_hashes = source_marker.get("file_sha256", {})
    marker_hash = marker_hashes.get("weather_daily") if isinstance(marker_hashes, dict) else None
    if marker_hash != source_sha256:
        raise DataQualityError(
            "Open-Meteo weather CSV does not match _DATAFORGE_SOURCE.json; "
            "restore a consistent source/provenance pair before ingest"
        )

    sidecar = source_dir / PROVENANCE_DIR / "weather_provenance.json"
    try:
        provenance = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DataQualityError(
            f"Open-Meteo weather provenance is missing or invalid at {sidecar}"
        ) from exc
    if (
        not isinstance(provenance, dict)
        or provenance.get("status") != "complete"
        or provenance.get("weather_csv_sha256") != source_sha256
        or provenance.get("weather_csv_rows") != row_count
    ):
        raise DataQualityError(
            "Open-Meteo weather CSV, source marker, and weather_provenance.json "
            "do not describe the same complete snapshot; restore a consistent pair before ingest"
        )


def _active_sources(specs: dict[str, dict]) -> tuple[str | None, dict[str, dict]]:
    """Load the active immutable manifest; reject a broken pointer rather than guessing."""
    pointer_path = MANIFESTS / "active.json"
    if not pointer_path.is_file():
        # Upgrade runs may have only the original per-source manifests. Import
        # those once so the first active subset run does not hide prior sources.
        legacy_sources = {}
        try:
            for name in specs:
                mirror_path = MANIFESTS / f"{name}.json"
                if not mirror_path.is_file():
                    continue
                metadata = json.loads(mirror_path.read_text(encoding="utf-8"))
                if (not isinstance(metadata, dict) or metadata.get("source") != name
                        or not metadata.get("source_sha256")
                        or not metadata.get("bronze_file")):
                    raise DataQualityError(f"legacy manifest has invalid metadata for {name}")
                legacy_sources[name] = metadata
        except (OSError, json.JSONDecodeError) as exc:
            raise DataQualityError(f"cannot read legacy source manifests: {exc}") from exc
        return None, legacy_sources
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        run_id = pointer.get("run_id") if isinstance(pointer, dict) else None
        if (not isinstance(run_id, str) or len(run_id) != 32
                or any(char not in "0123456789abcdef" for char in run_id)):
            raise DataQualityError("active manifest pointer has an invalid run_id")
        run_path = MANIFESTS / "runs" / f"{run_id}.json"
        run = json.loads(run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataQualityError(f"cannot read active ingestion run: {exc}") from exc
    if (not isinstance(run, dict) or run.get("run_id") != run_id
            or run.get("status") != "complete"
            or not isinstance(run.get("sources"), dict)):
        raise DataQualityError("active ingestion run is incomplete or malformed")
    sources = run["sources"]
    unknown = set(sources) - set(specs)
    if unknown:
        raise DataQualityError(f"active ingestion run has unknown sources: {sorted(unknown)}")
    for name, metadata in sources.items():
        if (not isinstance(metadata, dict) or metadata.get("source") != name
                or not metadata.get("source_sha256") or not metadata.get("bronze_file")):
            raise DataQualityError(f"active ingestion run has invalid metadata for {name}")
    return run_id, sources


def ingest(source_dir: Path = SOURCE, sources: list[str] | None = None) -> dict[str, dict]:
    specs = contracts()
    selected = list(dict.fromkeys(sources or list(specs)))
    unknown = set(selected) - set(specs)
    if unknown:
        raise DataQualityError(f"unknown sources: {sorted(unknown)}")
    results: dict[str, dict] = {}
    run_id = uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat()
    run_path = MANIFESTS / "runs" / f"{run_id}.json"
    current_source: str | None = None
    try:
        _write_json_atomically(run_path, {
            "run_id": run_id,
            "status": "running",
            "started_at_utc": started_at,
            "sources_requested": selected,
        })
        previous_run_id, previous_sources = _active_sources(specs)
        marker = source_dir / "_DATAFORGE_SOURCE.json"
        source_provenance = (
            json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
        )
        for name in selected:
            current_source = name
            csv_path = source_dir / f"{name}.csv"
            if not csv_path.is_file():
                raise FileNotFoundError(
                    f"missing {csv_path}; run `dataforge generate` or provide CSV"
                )
            source_sha = hashlib.sha256(csv_path.read_bytes()).hexdigest()
            expected_sha = source_provenance.get("file_sha256", {}).get(name)
            provenance = (source_provenance.get("source_overrides", {}).get(name)
                          or source_provenance.get("dataset_class", "unverified_manual"))
            if expected_sha != source_sha:
                provenance = "unverified_modified_source"
            df = pd.read_csv(csv_path, dtype="string", keep_default_na=False)
            validate(df, name)
            if name == "weather_daily":
                _validate_weather_provenance(source_dir, source_provenance, source_sha, len(df))
            out_dir = BRONZE / name / f"sha256={source_sha}"
            out_dir.mkdir(parents=True, exist_ok=True)
            parquet = out_dir / "part-000.parquet"
            try:
                buffer = io.BytesIO()
                df.to_parquet(buffer, engine="pyarrow", index=False)
            except ImportError as exc:
                raise RuntimeError(
                    "Parquet requires pyarrow; install with `pip install -e .[dev]`"
                ) from exc
            parquet_bytes = buffer.getvalue()
            bronze_sha = hashlib.sha256(parquet_bytes).hexdigest()
            previous = previous_sources.get(name, {})
            previous_path = previous.get("bronze_file") if isinstance(previous, dict) else None
            previous_sha = previous.get("bronze_sha256") if isinstance(previous, dict) else None
            same_previous_artifact = (
                previous.get("source_sha256") == source_sha
                and isinstance(previous_path, str)
                and Path(previous_path).resolve() == parquet.resolve()
            ) if isinstance(previous, dict) else False
            if parquet.exists():
                actual_bronze_sha = hashlib.sha256(parquet.read_bytes()).hexdigest()
                if same_previous_artifact and previous_sha:
                    if actual_bronze_sha != previous_sha:
                        raise DataQualityError(
                            f"existing bronze Parquet for {name} failed its recorded SHA-256; "
                            "preserve the artifact and restore from a trusted backup"
                        )
                elif actual_bronze_sha != bronze_sha:
                    raise DataQualityError(
                        f"unverified legacy/orphan bronze Parquet for {name} does not match "
                        "the validated source CSV; preserve it and restore the source or use "
                        "a fresh, isolated bronze directory"
                    )
                verified_sha = actual_bronze_sha
            else:
                _write_parquet_atomically(parquet, parquet_bytes, run_id)
                verified_sha = hashlib.sha256(parquet.read_bytes()).hexdigest()
            if same_previous_artifact and previous_sha and verified_sha != previous_sha:
                raise DataQualityError(
                    f"existing bronze Parquet for {name} failed its recorded SHA-256"
                )
            read_verified_bronze(
                parquet,
                source=name,
                expected_sha256=verified_sha,
                expected_columns=specs[name]["required_columns"],
                expected_rows=len(df),
            )
            results[name] = {
                "source": name,
                "source_file": str(csv_path.resolve()),
                "source_sha256": source_sha,
                "bronze_file": str(parquet.resolve()),
                "bronze_sha256": verified_sha,
                "rows_accepted": len(df),
                "rows_rejected": 0,
                "processed_at_utc": datetime.now(timezone.utc).isoformat(),
                "data_classification": provenance,
                "ingest_run_id": run_id,
            }

        complete_sources = {**previous_sources, **results}
        completed_at = datetime.now(timezone.utc).isoformat()
        complete_run = {
            "run_id": run_id,
            "status": "complete",
            "started_at_utc": started_at,
            "completed_at_utc": completed_at,
            "previous_run_id": previous_run_id,
            "sources_requested": selected,
            "sources": complete_sources,
        }
        # The run becomes immutable and complete before the single active pointer moves.
        _write_json_atomically(run_path, complete_run)
        _write_json_atomically(MANIFESTS / "active.json", {"run_id": run_id})

        # Compatibility mirrors are non-authoritative once active.json exists.
        for name, metadata in complete_sources.items():
            try:
                _write_json_atomically(MANIFESTS / f"{name}.json", metadata)
            except Exception as exc:  # The committed active run remains usable.
                logger.warning("could not refresh compatibility manifest for %s: %s", name, exc)
    except Exception as exc:
        failed_run = {
            "run_id": run_id,
            "status": "failed",
            "started_at_utc": started_at,
            "failed_at_utc": datetime.now(timezone.utc).isoformat(),
            "sources_requested": selected,
            "prepared_sources": sorted(results),
            "failed_source": current_source,
            "error": f"{type(exc).__name__}: {exc}",
        }
        try:
            _write_json_atomically(run_path, failed_run)
        except Exception as record_exc:
            exc.add_note(f"Could not persist failed ingestion run record: {record_exc}")
        raise
    return results
