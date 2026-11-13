from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "week1_fetch_csv.sh"
FIXTURE = Path(__file__).parent / "fixtures" / "weather.csv"


def _bash_executable() -> str:
    if os.name == "nt":
        for candidate in (
            Path(r"C:\Program Files\Git\bin\bash.exe"),
            Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
        ):
            if candidate.is_file():
                return str(candidate)
        pytest.skip("Git Bash is unavailable; run these fixtures in Git Bash or Linux CI")
    executable = shutil.which("bash")
    if executable:
        return executable
    pytest.skip("Bash is unavailable; Week 1 shell tests run in Linux CI")


@contextmanager
def _serve_csv(
    body: bytes,
    *,
    failures_before_success: int = 0,
) -> Iterator[tuple[str, ThreadingHTTPServer]]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.server.request_count += 1
            if self.path != "/fixture.csv":
                self.send_error(404)
                return
            if self.server.failures_before_success:
                self.server.failures_before_success -= 1
                self.send_error(503, "temporary fixture failure")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            response_body = self.server.body
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.body = body
    server.failures_before_success = failures_before_success
    server.request_count = 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}/fixture.csv", server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _run(
    *,
    url: str,
    output_dir: Path,
    date: str | None = "2026-11-13",
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    arguments = [
        _bash_executable(),
        str(SCRIPT),
        "--url",
        url,
        "--output-dir",
        str(output_dir),
    ]
    if date is not None:
        arguments.extend(("--date", date))
    return subprocess.run(
        arguments,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )


def test_success_publishes_gzip_and_provenance_with_logical_row_count(tmp_path: Path) -> None:
    expected_csv = FIXTURE.read_bytes()
    output_dir = tmp_path / "path with spaces"
    with _serve_csv(expected_csv) as (url, _):
        result = _run(url=url, output_dir=output_dir)

    assert result.returncode == 0, result.stderr
    assert "PASS: 2 rows" in result.stdout
    partition = output_dir / "2026-11-13"
    gzip_files = list(partition.glob("*.csv.gz"))
    manifests = list(partition.glob("*.manifest.json"))
    assert len(gzip_files) == 1
    assert len(manifests) == 1
    assert gzip_files[0].name.startswith("weather-")
    assert len(gzip_files[0].name.removeprefix("weather-").removesuffix(".csv.gz")) == 64
    assert gzip.decompress(gzip_files[0].read_bytes()) == expected_csv

    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    assert manifest["status"] == "COMPLETE"
    assert manifest["partition_timezone"] == "Asia/Bangkok"
    assert manifest["row_count_excluding_header"] == 2
    assert manifest["csv_sha256"] == hashlib.sha256(expected_csv).hexdigest()
    assert manifest["csv_size_bytes"] == len(expected_csv)
    archive = gzip_files[0].read_bytes()
    assert manifest["gzip_sha256"] == hashlib.sha256(archive).hexdigest()
    assert manifest["gzip_size_bytes"] == len(archive)
    assert manifest["recorded_at_utc"].endswith("Z")
    assert manifest["source_url"] == url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.org/data.csv",
        "https://user:password@example.org/data.csv",
        "https://example.org/data.csv?token=secret",
        "http://example.org/data.csv",
    ],
)
def test_rejects_unsafe_or_non_https_urls_before_creating_partition(
    url: str,
    tmp_path: Path,
) -> None:
    result = _run(url=url, output_dir=tmp_path)

    assert result.returncode == 2
    assert "URL must be public HTTPS" in result.stderr
    assert not (tmp_path / "2026-11-13").exists()


def test_default_partition_date_uses_asia_bangkok_timezone(tmp_path: Path) -> None:
    before = datetime.now(ZoneInfo("Asia/Bangkok")).date().isoformat()
    with _serve_csv(FIXTURE.read_bytes()) as (url, _):
        result = _run(url=url, output_dir=tmp_path, date=None)
    after = datetime.now(ZoneInfo("Asia/Bangkok")).date().isoformat()

    assert result.returncode == 0, result.stderr
    observed_dates = {path.name for path in tmp_path.iterdir() if path.is_dir()}
    assert observed_dates & {before, after}
    manifest_path = next(tmp_path.glob("*/weather-*.manifest.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["partition_timezone"] == "Asia/Bangkok"
    assert manifest["partition_date"] in {before, after}


def test_rejects_invalid_calendar_date_before_creating_partition(tmp_path: Path) -> None:
    result = _run(
        url="http://127.0.0.1:1/unused.csv",
        output_dir=tmp_path,
        date="2026-02-30",
    )

    assert result.returncode == 2
    assert "--date must be a real ISO YYYY-MM-DD date" in result.stderr
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"\n",
        b"date,,value\n2026-11-12,0,1\n",
        b"date,value\n2026-11-12\n",
        b"date,value\n",
    ],
)
def test_rejects_empty_or_malformed_csv_without_published_artifacts(
    body: bytes,
    tmp_path: Path,
) -> None:
    with _serve_csv(body) as (url, _):
        result = _run(url=url, output_dir=tmp_path)

    assert result.returncode == 2
    assert "CSV" in result.stderr
    partition = tmp_path / "2026-11-13"
    assert not list(partition.glob("*.csv.gz"))
    assert not list(partition.glob("*.manifest.json"))
    assert not list(partition.glob(".week1-*"))


def test_same_url_and_content_is_a_verified_noop_on_replay(tmp_path: Path) -> None:
    with _serve_csv(FIXTURE.read_bytes()) as (url, _):
        first = _run(url=url, output_dir=tmp_path)
        before = {
            path.name: path.read_bytes()
            for path in (tmp_path / "2026-11-13").iterdir()
        }
        second = _run(url=url, output_dir=tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "NOOP: verified existing partition" in second.stdout
    after = {
        path.name: path.read_bytes()
        for path in (tmp_path / "2026-11-13").iterdir()
    }
    assert after == before


def test_changed_source_content_gets_a_new_version_without_replacing_old_data(
    tmp_path: Path,
) -> None:
    original = FIXTURE.read_bytes()
    corrected = original + b"2026-11-13,0.0,9.1,4.5,3.2,rain\n"
    with _serve_csv(original) as (url, server):
        first = _run(url=url, output_dir=tmp_path)
        old_archive = next((tmp_path / "2026-11-13").glob("*.csv.gz"))
        old_bytes = old_archive.read_bytes()

        server.body = corrected
        second = _run(url=url, output_dir=tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "PASS: 3 rows" in second.stdout
    assert old_archive.read_bytes() == old_bytes
    archives = list((tmp_path / "2026-11-13").glob("*.csv.gz"))
    manifests = list((tmp_path / "2026-11-13").glob("*.manifest.json"))
    assert len(archives) == len(manifests) == 2
    assert len({archive.name for archive in archives}) == 2
    manifest_values = [
        json.loads(manifest.read_text(encoding="utf-8")) for manifest in manifests
    ]
    assert {manifest["source_url"] for manifest in manifest_values} == {url}
    assert {manifest["csv_sha256"] for manifest in manifest_values} == {
        hashlib.sha256(original).hexdigest(),
        hashlib.sha256(corrected).hexdigest(),
    }


def test_corrupt_replay_fails_closed_without_replacing_the_existing_archive(
    tmp_path: Path,
) -> None:
    with _serve_csv(FIXTURE.read_bytes()) as (url, _):
        first = _run(url=url, output_dir=tmp_path)
        archive = next((tmp_path / "2026-11-13").glob("*.csv.gz"))
        archive.write_bytes(archive.read_bytes() + b"corruption")
        corrupted_bytes = archive.read_bytes()
        second = _run(url=url, output_dir=tmp_path)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 2
    assert "no existing file was replaced" in second.stderr
    assert archive.read_bytes() == corrupted_bytes


def test_retries_one_transient_503_using_only_the_loopback_fixture(tmp_path: Path) -> None:
    with _serve_csv(FIXTURE.read_bytes(), failures_before_success=1) as (url, server):
        result = _run(url=url, output_dir=tmp_path)

    assert result.returncode == 0, result.stderr
    assert server.request_count == 2
    assert "PASS: 2 rows" in result.stdout
    assert len(list((tmp_path / "2026-11-13").glob("*.csv.gz"))) == 1
