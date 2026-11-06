"""Optional real API ingestion using the documented Open-Meteo archive endpoint."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

import requests

from .settings import SOURCE

# Coordinates are approximate city centres; they are not street-level location data.
CITY_LOCATIONS = {"HCM": (10.8231, 106.6297), "HN": (21.0285, 105.8542), "DN": (16.0544, 108.2022)}
API = "https://archive-api.open-meteo.com/v1/archive"
DAILY_FIELDS = ("precipitation_sum", "temperature_2m_max")
TIMEZONE = "Asia/Ho_Chi_Minh"
MODEL = "era5"
PROVENANCE_DIR = ".open_meteo"


def _response_body(response, payload: object | None) -> tuple[bytes, str]:
    content = getattr(response, "content", None)
    if isinstance(content, str) and content:
        return content.encode("utf-8"), "response_content"
    if isinstance(content, (bytes, bytearray, memoryview)) and content:
        return bytes(content), "response_content"
    text = getattr(response, "text", None)
    if isinstance(text, str) and text:
        return text.encode("utf-8"), "response_text"
    if payload is not None:
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return canonical, "canonical_json"
    return b"", "empty_body"


def _response_evidence(response, province: str, attempt: int,
                       payload: object | None = None) -> dict:
    body, hash_basis = _response_body(response, payload)
    return {
        "province_id": province,
        "attempt": attempt,
        "http_status": getattr(response, "status_code", None),
        "response_sha256": hashlib.sha256(body).hexdigest(),
        "hash_basis": hash_basis,
        "_raw_response_bytes": body,
    }


def _stage_bytes(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.{uuid4().hex}.stage")
    with staged.open("xb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    return staged


def _replace_staged(staged: Path, path: Path) -> None:
    os.replace(staged, path)


def _atomic_bytes(path: Path, content: bytes) -> None:
    staged = _stage_bytes(path, content)
    try:
        _replace_staged(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _atomic_json(path: Path, value: dict) -> None:
    content = json.dumps(value, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    _atomic_bytes(path, content)


def _backup_weather_files(
    csv_path: Path,
    marker_path: Path,
    provenance_path: Path,
    previous: dict[Path, bytes | None],
) -> Path | None:
    backup_targets = {
        csv_path: "weather_daily.csv",
        marker_path: "_DATAFORGE_SOURCE.json",
        provenance_path: "weather_provenance.json",
    }
    existing = [(path, previous[path]) for path in backup_targets if previous[path] is not None]
    if not existing:
        return None
    backup_root = provenance_path.parent / "transactions" / uuid4().hex
    created = False
    try:
        backup_root.mkdir(parents=True, exist_ok=False)
        created = True
        files = {}
        for path, content in existing:
            assert content is not None
            filename = backup_targets[path]
            _atomic_bytes(backup_root / filename, content)
            files[filename] = {
                "present": True,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        for path, filename in backup_targets.items():
            if filename not in files:
                files[filename] = {"present": False, "sha256": None}
        _atomic_json(backup_root / "manifest.json", {
            "transaction_id": backup_root.name,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "files": files,
        })
    except Exception:
        if created:
            _remove_backup_directory(backup_root)
        raise
    return backup_root


def _remove_backup_directory(path: Path | None) -> None:
    if path is None or not path.is_dir():
        return
    for child in path.iterdir():
        if child.is_file():
            child.unlink()
        else:
            raise OSError(f"unexpected directory in weather rollback backup: {child}")
    path.rmdir()


def _response_json_artifact(dest: Path, evidence: dict) -> tuple[Path | None, str | None, bytes | None]:
    body = evidence.get("_raw_response_bytes", b"")
    if not body:
        return None, None, None
    try:
        json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None, None
    digest = evidence["response_sha256"]
    path = (dest / PROVENANCE_DIR / "responses" / evidence["province_id"]
            / f"sha256={digest}.json")
    if path.is_file():
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            raise ValueError(f"existing Open-Meteo response artifact has a digest mismatch: {path}")
        return path, path.relative_to(dest).as_posix(), None
    return path, path.relative_to(dest).as_posix(), body


def _publish_weather_outputs(
    csv_path: Path,
    marker_path: Path,
    provenance_path: Path,
    csv_bytes: bytes,
    marker_bytes: bytes,
    provenance_bytes: bytes,
    raw_response_updates: dict[Path, bytes],
) -> None:
    """Stage all outputs and restore prior files if any promotion fails."""
    outputs = {
        **raw_response_updates,
        marker_path: marker_bytes,
        provenance_path: provenance_bytes,
        csv_path: csv_bytes,
    }
    previous = {
        path: path.read_bytes() if path.is_file() else None
        for path in outputs
    }
    staged: dict[Path, Path] = {}
    promoted: list[Path] = []
    backup_root: Path | None = None
    try:
        for path, content in outputs.items():
            staged[path] = _stage_bytes(path, content)

        backup_root = _backup_weather_files(
            csv_path, marker_path, provenance_path, previous
        )

        # The CSV is the commit point: do not replace the prior source until
        # its matching marker, provenance, and raw response evidence are staged.
        promotion_order = [
            *raw_response_updates,
            marker_path,
            provenance_path,
            csv_path,
        ]
        for path in promotion_order:
            _replace_staged(staged[path], path)
            promoted.append(path)
    except Exception as exc:
        rollback_errors = []
        for path in reversed(promoted):
            try:
                old_bytes = previous[path]
                if old_bytes is None:
                    path.unlink(missing_ok=True)
                else:
                    _atomic_bytes(path, old_bytes)
            except Exception as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        if rollback_errors:
            exc.add_note(
                "Could not restore every prior weather output: "
                + "; ".join(rollback_errors)
                + f". Prior files, if present, are preserved at {backup_root}"
            )
        else:
            _remove_backup_directory(backup_root)
        raise
    else:
        _remove_backup_directory(backup_root)
    finally:
        for staged_path in staged.values():
            staged_path.unlink(missing_ok=True)


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def parse_daily(payload: object, province: str) -> list[tuple]:
    if not isinstance(payload, dict):
        raise ValueError("API response must be a JSON object")
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise ValueError("API response missing `daily` data")
    dates = daily.get("time")
    rains = daily.get("precipitation_sum")
    temps = daily.get("temperature_2m_max")
    if not all(isinstance(values, list) for values in (dates, rains, temps)):
        raise ValueError("API response daily fields must be JSON arrays")
    if not (len(dates) == len(rains) == len(temps) and len(dates) > 0):
        raise ValueError("API response daily arrays have mismatched lengths")
    for day, rain, temp in zip(dates, rains, temps):
        if not isinstance(day, str):
            raise ValueError("API response contains a non-string observation date")
        try:
            parsed_day = date.fromisoformat(day)
        except ValueError as exc:
            raise ValueError(f"API response contains an invalid observation date: {day}") from exc
        if parsed_day.isoformat() != day:
            raise ValueError(f"API response contains a non-canonical observation date: {day}")
        if rain is not None and (not _is_finite_number(rain) or rain < 0):
            raise ValueError(f"API response contains invalid precipitation for {day}")
        if temp is not None and not _is_finite_number(temp):
            raise ValueError(f"API response contains invalid maximum temperature for {day}")
    return [(province, d, r, t, "open_meteo_era5") for d, r, t in zip(dates, rains, temps)]


def fetch(start: date, end: date, provinces: list[str] | None = None,
          dest: Path = SOURCE, requester: Callable | None = None) -> int:
    if end < start:
        raise ValueError("end must be on or after start")
    if (end - start).days > 366:
        raise ValueError("limit one request batch to 367 days; split longer backfills")
    if end >= date.today():
        raise ValueError("historical requests must end before today; ERA5 data can have lag")
    provinces = provinces or list(CITY_LOCATIONS)
    if any(p not in CITY_LOCATIONS for p in provinces):
        raise ValueError(f"allowed provinces: {list(CITY_LOCATIONS)}")
    if len(set(provinces)) != len(provinces):
        raise ValueError("provinces must not contain duplicates")
    marker_path = dest / "_DATAFORGE_SOURCE.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8")) if marker_path.is_file() else {}
    if not isinstance(marker, dict):
        raise ValueError("source provenance marker must be a JSON object")
    file_hashes = marker.get("file_sha256", {})
    source_overrides = marker.get("source_overrides", {})
    if not isinstance(file_hashes, dict):
        raise ValueError("source provenance file_sha256 must be a JSON object")
    if not isinstance(source_overrides, dict):
        raise ValueError("source provenance source_overrides must be a JSON object")
    if any(not isinstance(name, str) or not isinstance(value, str)
           for name, value in file_hashes.items()):
        raise ValueError("source provenance file_sha256 entries must be strings")
    if any(not isinstance(name, str) or not isinstance(value, str)
           for name, value in source_overrides.items()):
        raise ValueError("source provenance source_overrides entries must be strings")
    dataset_class = marker.get("dataset_class")
    if dataset_class is not None and not isinstance(dataset_class, str):
        raise ValueError("source provenance dataset_class must be a string")
    http = requester or requests.get
    rows = []
    response_evidence = []
    for p in provinces:
        lat, lon = CITY_LOCATIONS[p]
        params = {
            "latitude": lat, "longitude": lon,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "daily": ",".join(DAILY_FIELDS),
            "timezone": TIMEZONE, "models": MODEL,
        }
        last_exc = None
        for attempt in range(1, 4):
            try:
                response = http(API, params=params, timeout=(5, 40))
            except requests.HTTPError as exc:
                last_exc = exc
            except requests.RequestException as exc:
                last_exc = exc
            else:
                status = getattr(response, "status_code", None)
                try:
                    response.raise_for_status()
                except requests.HTTPError as exc:
                    evidence = _response_evidence(response, p, attempt)
                    if status is None and exc.response is not None:
                        evidence["http_status"] = exc.response.status_code
                        status = exc.response.status_code
                    response_evidence.append(evidence)
                    retryable = status is None or status in {408, 425, 429} or status >= 500
                    if not retryable:
                        raise RuntimeError(
                            f"Open-Meteo returned non-retryable HTTP {status} for {p}"
                        ) from exc
                    last_exc = exc
                except requests.RequestException as exc:
                    response_evidence.append(_response_evidence(response, p, attempt))
                    last_exc = exc
                else:
                    try:
                        payload = response.json()
                    except requests.RequestException as exc:
                        response_evidence.append(_response_evidence(response, p, attempt))
                        last_exc = exc
                    except ValueError as exc:
                        response_evidence.append(_response_evidence(response, p, attempt))
                        raise RuntimeError(
                            f"Open-Meteo returned invalid response data for {p}"
                        ) from exc
                    else:
                        response_evidence.append(
                            _response_evidence(response, p, attempt, payload)
                        )
                        try:
                            parsed_rows = parse_daily(payload, p)
                            expected_dates = [
                                (start + timedelta(days=offset)).isoformat()
                                for offset in range((end - start).days + 1)
                            ]
                            observed_dates = [row[1] for row in parsed_rows]
                            if observed_dates != expected_dates:
                                raise ValueError(
                                    f"unexpected date coverage for {p}: "
                                    f"expected {len(expected_dates)} consecutive dates "
                                    f"from {start} to {end}; got {observed_dates[:3]}..."
                                )
                            rows.extend(parsed_rows)
                        except ValueError as exc:
                            raise RuntimeError(
                                f"Open-Meteo returned invalid daily data for {p}"
                            ) from exc
                        last_exc = None
                        break
            if attempt < 3:
                time.sleep(min(2 ** (attempt - 1), 4))
        if last_exc:
            raise RuntimeError(f"Open-Meteo fetch failed for {p} after 3 attempts") from last_exc
    path = dest / "weather_daily.csv"
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer)
    writer.writerow(["province_id", "observation_date", "precipitation_mm", "temp_max_c", "source"])
    writer.writerows(rows)
    csv_bytes = csv_buffer.getvalue().encode("utf-8")
    weather_sha = hashlib.sha256(csv_bytes).hexdigest()

    new_marker = dict(marker)
    new_marker["file_sha256"] = {**file_hashes, "weather_daily": weather_sha}
    new_marker["source_overrides"] = {
        **source_overrides,
        "weather_daily": "open_meteo_era5",
    }
    marker_bytes = json.dumps(new_marker, indent=2, ensure_ascii=False).encode("utf-8")

    response_records = []
    raw_response_updates: dict[Path, bytes] = {}
    for evidence in response_evidence:
        raw_path, relative_path, raw_bytes = _response_json_artifact(dest, evidence)
        if raw_path is not None and raw_bytes is not None:
            raw_response_updates[raw_path] = raw_bytes
        record = {key: value for key, value in evidence.items()
                  if key != "_raw_response_bytes"}
        record["raw_response_json"] = relative_path
        response_records.append(record)

    provenance = {
        "status": "complete",
        "provider": "Open-Meteo",
        "endpoint": API,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "date_range": {"start": start.isoformat(), "end": end.isoformat()},
        "requested_provinces": [
            {"province_id": p, "latitude": CITY_LOCATIONS[p][0],
             "longitude": CITY_LOCATIONS[p][1]}
            for p in provinces
        ],
        "daily_fields": list(DAILY_FIELDS),
        "timezone": TIMEZONE,
        "model": MODEL,
        "responses": response_records,
        "weather_csv_sha256": weather_sha,
        "weather_csv_rows": len(rows),
        "attribution": {
            "text": (
                "Weather data from Open-Meteo.com Historical Weather API, model ERA5. "
                "Selected daily values were transformed to province-level CSV rows."
            ),
            "provider_url": "https://open-meteo.com/",
            "api_documentation_url": "https://open-meteo.com/en/docs/historical-weather-api",
            "data_license": "CC BY 4.0",
            "license_url": "https://open-meteo.com/en/terms",
        },
    }
    provenance_path = dest / PROVENANCE_DIR / "weather_provenance.json"
    provenance_bytes = (
        json.dumps(provenance, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    )
    _publish_weather_outputs(
        path,
        marker_path,
        provenance_path,
        csv_bytes,
        marker_bytes,
        provenance_bytes,
        raw_response_updates,
    )
    return len(rows)
