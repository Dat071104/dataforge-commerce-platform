"""Download the fixed Week 6 NYC TLC source files with local integrity receipts.

Raw data and generated receipts belong in a scratch directory outside the Git
checkout. The default is a directory beneath the system temporary directory;
set ``DATAFORGE_SPARK_DATA_DIR`` to a persistent scratch mount when needed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TLC_PAGE_URL = "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page"
TLC_DATA_BASE_URL = "https://d37ci6vzurychx.cloudfront.net"
ZONE_LOOKUP_URL = f"{TLC_DATA_BASE_URL}/misc/taxi_zone_lookup.csv"
DEFAULT_MONTHS = (1, 2, 3, 4)
YEAR = 2024
CHUNK_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 60
MANIFEST_NAME = "source_manifest.json"
USER_AGENT = "DataForge-P7.3-Week6-Lab/1.0 (research reproducibility)"


class DownloadError(RuntimeError):
    """A source download or local integrity check failed."""


@dataclass(frozen=True)
class DownloadReceipt:
    name: str
    source_url: str
    local_path: str
    bytes: int
    sha256: str
    status: str
    etag: str | None = None
    last_modified: str | None = None
    row_count: str = "NOT_RUN"


def default_data_dir() -> Path:
    """Return a scratch path outside the repository unless explicitly set."""

    configured = os.environ.get("DATAFORGE_SPARK_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(tempfile.gettempdir()) / "dataforge-spark-nyc-taxi"


def monthly_url(year: int, month: int) -> str:
    """Build the official Yellow Taxi Parquet URL for one calendar month."""

    if year != YEAR:
        raise ValueError(f"This lab pins Yellow Taxi source schema year {YEAR}; got {year}")
    if not 1 <= month <= 12:
        raise ValueError(f"month must be in 1..12; got {month}")
    return f"{TLC_DATA_BASE_URL}/trip-data/yellow_tripdata_{year}-{month:02d}.parquet"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _header(response: Any, name: str) -> str | None:
    value = response.headers.get(name)
    return str(value) if value is not None else None


def _download_atomic(
    url: str,
    destination: Path,
    timeout: int = TIMEOUT_SECONDS,
    *,
    resume_existing_partial: bool = True,
) -> DownloadReceipt:
    """Stream one URL to a resumable partial file, then atomically publish it."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".partial")
    if partial.exists() and not resume_existing_partial:
        partial.unlink()
    offset = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"

    request = Request(url, headers=headers)
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        if exc.code == 416 and offset:
            # A completed stale partial cannot be distinguished from a full
            # current source by its name alone; restart once without Range.
            partial.unlink(missing_ok=True)
            return _download_atomic(
                url,
                destination,
                timeout,
                resume_existing_partial=False,
            )
        raise DownloadError(f"GET failed for {url}: {exc}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise DownloadError(f"GET failed for {url}: {exc}") from exc

    with response:
        status = int(getattr(response, "status", response.getcode()))
        if status not in (200, 206):
            raise DownloadError(f"GET {url} returned HTTP {status}")

        content_range = _header(response, "Content-Range")
        append = status == 206 and offset > 0
        if append:
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", content_range or "")
            if not match or int(match.group(1)) != offset:
                raise DownloadError(
                    f"invalid Content-Range while resuming {url}: {content_range!r}"
                )
            expected_total = None if match.group(3) == "*" else int(match.group(3))
            expected_transfer = int(match.group(2)) - int(match.group(1)) + 1
        else:
            # A server that ignores Range returns 200; restart the partial file.
            offset = 0
            expected_total = _parse_nonnegative_int(_header(response, "Content-Length"))
            expected_transfer = expected_total

        mode = "ab" if append else "wb"
        received = 0
        try:
            with partial.open(mode) as target:
                while block := response.read(CHUNK_BYTES):
                    target.write(block)
                    received += len(block)
                target.flush()
                os.fsync(target.fileno())
        except OSError as exc:
            raise DownloadError(f"failed writing {partial}: {exc}") from exc

        if expected_transfer is not None and received != expected_transfer:
            raise DownloadError(
                f"short response for {url}: received {received} bytes; expected {expected_transfer}"
            )
        actual_size = partial.stat().st_size
        if expected_total is not None and actual_size != expected_total:
            raise DownloadError(
                f"incomplete file for {url}: have {actual_size} bytes; expected {expected_total}"
            )
        if actual_size == 0:
            raise DownloadError(f"empty response for {url}")

        digest = _sha256(partial)
        os.replace(partial, destination)
        return DownloadReceipt(
            name=destination.name,
            source_url=url,
            local_path=str(destination),
            bytes=actual_size,
            sha256=digest,
            status="DOWNLOADED",
            etag=_header(response, "ETag"),
            last_modified=_header(response, "Last-Modified"),
        )


def _parse_nonnegative_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _read_prior_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DownloadError(f"cannot read prior source manifest {path}: {exc}") from exc
    if not isinstance(loaded, dict) or not isinstance(loaded.get("files", []), list):
        raise DownloadError(f"source manifest has an unsupported shape: {path}")
    return loaded


def _existing_receipt(
    destination: Path,
    url: str,
    previous: dict[str, Any] | None,
) -> DownloadReceipt:
    if previous is None or not previous.get("sha256"):
        raise DownloadError(
            f"existing file has no prior SHA-256 receipt: {destination}; "
            "move it aside or pass refresh=True to replace it safely"
        )
    digest = _sha256(destination)
    if digest != previous["sha256"]:
        raise DownloadError(
            f"existing file digest differs from its manifest: {destination}; "
            "move it aside or pass refresh=True"
        )
    size = destination.stat().st_size
    if previous.get("bytes") is not None and size != int(previous["bytes"]):
        raise DownloadError(f"existing file size differs from its manifest: {destination}")
    return DownloadReceipt(
        name=destination.name,
        source_url=url,
        local_path=str(destination),
        bytes=size,
        sha256=digest,
        status="EXISTING_REHASHED",
        etag=previous.get("etag"),
        last_modified=previous.get("last_modified"),
        row_count="NOT_RUN",
    )


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    with temporary.open("w", encoding="utf-8", newline="\n") as target:
        target.write(encoded)
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


def download_sources(
    data_dir: str | Path | None = None,
    months: tuple[int, ...] = DEFAULT_MONTHS,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    """Download selected 2024 Yellow Taxi files and the official zone lookup.

    Existing files are re-hashed and compared with the prior local manifest.
    A file without that baseline is not trusted silently. ``refresh=True`` is
    explicit and publishes replacement data only after a complete response.
    """

    selected_months = tuple(months)
    if not selected_months or len(set(selected_months)) != len(selected_months):
        raise ValueError("months must be a non-empty sequence without duplicates")
    for month in selected_months:
        if not 1 <= month <= 12:
            raise ValueError(f"month must be in 1..12; got {month}")

    root = Path(data_dir).expanduser().resolve() if data_dir else default_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / MANIFEST_NAME
    prior = _read_prior_manifest(manifest_path)
    previous_by_name = {entry.get("name"): entry for entry in prior.get("files", [])}

    files = [
        (f"yellow_tripdata_{YEAR}-{month:02d}.parquet", monthly_url(YEAR, month))
        for month in selected_months
    ]
    files.append(("taxi_zone_lookup.csv", ZONE_LOOKUP_URL))
    receipts: list[DownloadReceipt] = []
    body: dict[str, Any] = {
        "status": "IN_PROGRESS",
        "source_page_url": TLC_PAGE_URL,
        "schema_period": (
            f"{YEAR}-{selected_months[0]:02d} through "
            f"{YEAR}-{selected_months[-1]:02d}"
        ),
        "accessed_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": [],
        "row_counts": "NOT_RUN",
    }
    _atomic_json(manifest_path, body)

    for name, url in files:
        destination = root / name
        if destination.exists() and not refresh:
            receipt = _existing_receipt(destination, url, previous_by_name.get(name))
        else:
            receipt = _download_atomic(
                url,
                destination,
                resume_existing_partial=not refresh,
            )
        receipts.append(receipt)
        body["files"] = [asdict(item) for item in receipts]
        _atomic_json(manifest_path, body)

    body["status"] = "COMPLETE"
    body["files"] = [asdict(item) for item in receipts]
    body["row_counts"] = "NOT_RUN"
    _atomic_json(manifest_path, body)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--months", type=int, nargs="+", default=list(DEFAULT_MONTHS))
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="explicitly redownload even if source files already exist",
    )
    args = parser.parse_args(argv)
    try:
        receipt = download_sources(args.data_dir, tuple(args.months), refresh=args.refresh)
    except (DownloadError, OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
