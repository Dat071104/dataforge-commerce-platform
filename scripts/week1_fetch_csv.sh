#!/usr/bin/env bash
set -Eeuo pipefail

# Week 1 shell exercise: fetch one public CSV, validate it, and publish a
# content-addressed gzip plus provenance manifest under a local date partition.

readonly DEFAULT_URL="https://cdn.jsdelivr.net/npm/vega-datasets@3.3.1/data/seattle-weather.csv"
readonly PARTITION_TIMEZONE="Asia/Bangkok"
readonly MAX_DOWNLOAD_BYTES=10485760

usage() {
  cat <<'USAGE'
Usage: scripts/week1_fetch_csv.sh [--url HTTPS_URL] [--output-dir DIR] [--date YYYY-MM-DD]

Fetch a public CSV and write:
  DIR/YYYY-MM-DD/weather-<record-id>.csv.gz
  DIR/YYYY-MM-DD/weather-<record-id>.manifest.json

The default date uses Asia/Bangkok. --date makes a run reproducible and is
useful for backfills. HTTPS is required, except for an explicit loopback HTTP
URL used by offline tests. URL credentials, query strings, and fragments are
rejected so the provenance manifest cannot record an accidental token.
USAGE
}

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

source_url="$DEFAULT_URL"
output_root=".local/week1"
requested_date=""

while (($#)); do
  case "$1" in
    --url)
      (($# >= 2)) || die "--url requires a value"
      source_url="$2"
      shift 2
      ;;
    --output-dir)
      (($# >= 2)) || die "--output-dir requires a value"
      output_root="$2"
      shift 2
      ;;
    --date)
      (($# >= 2)) || die "--date requires a value"
      requested_date="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

if [[ -n "$requested_date" ]]; then
  if ! python - "$requested_date" >/dev/null 2>&1 <<'PY'
from datetime import date
import sys

value = sys.argv[1]
parsed = date.fromisoformat(value)
if parsed.isoformat() != value:
    raise SystemExit(1)
PY
  then
    die "--date must be a real ISO YYYY-MM-DD date"
  fi
  partition_date="$requested_date"
else
  if ! partition_date="$(python - "$PARTITION_TIMEZONE" <<'PY'
from datetime import datetime
from zoneinfo import ZoneInfo
import sys

print(datetime.now(ZoneInfo(sys.argv[1])).date().isoformat())
PY
)"; then
    die "Python timezone data is required to calculate the Asia/Bangkok partition date"
  fi
fi

if ! python - "$source_url" >/dev/null 2>&1 <<'PY'
from ipaddress import ip_address
from urllib.parse import urlsplit
import sys

raw = sys.argv[1]
if not raw or any(character.isspace() or ord(character) < 32 for character in raw):
    raise SystemExit(1)
try:
    parsed = urlsplit(raw)
    host = parsed.hostname
    port = parsed.port
except ValueError:
    raise SystemExit(1)

if not host or parsed.username is not None or parsed.password is not None:
    raise SystemExit(1)
if parsed.query or parsed.fragment:
    raise SystemExit(1)

if parsed.scheme == "https":
    if port not in (None, 443):
        raise SystemExit(1)
    lowered = host.lower()
    if lowered == "localhost" or lowered.endswith((".localhost", ".local", ".internal")):
        raise SystemExit(1)
    try:
        address = ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise SystemExit(1)
elif parsed.scheme == "http":
    if host.lower() not in {"localhost", "127.0.0.1", "::1"} or port is None:
        raise SystemExit(1)
else:
    raise SystemExit(1)
PY
then
  die "URL must be public HTTPS without credentials/query/fragment, or explicit loopback HTTP for an offline test"
fi

if ! command -v curl >/dev/null 2>&1; then
  die "curl is required"
fi
if ! command -v gzip >/dev/null 2>&1; then
  die "gzip is required"
fi

partition_dir="$output_root/$partition_date"
mkdir -p "$partition_dir"

tmp_csv=""
tmp_gzip=""
tmp_manifest=""
cleanup() {
  [[ -z "$tmp_csv" ]] || rm -f "$tmp_csv"
  [[ -z "$tmp_gzip" ]] || rm -f "$tmp_gzip"
  [[ -z "$tmp_manifest" ]] || rm -f "$tmp_manifest"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
tmp_csv="$(mktemp "$partition_dir/.week1-csv.XXXXXX")"
tmp_gzip="$(mktemp "$partition_dir/.week1-gzip.XXXXXX")"
tmp_manifest="$(mktemp "$partition_dir/.week1-manifest.XXXXXX")"

curl_protocols="=https"
curl_max_redirs=5
if [[ "$source_url" == http://* ]]; then
  curl_protocols="=http,https"
  curl_max_redirs=0
fi
if ! curl \
  --fail \
  --location \
  --max-redirs "$curl_max_redirs" \
  --connect-timeout 5 \
  --max-time 30 \
  --max-filesize "$MAX_DOWNLOAD_BYTES" \
  --retry 2 \
  --retry-delay 0 \
  --retry-max-time 10 \
  --proto "$curl_protocols" \
  --proto-redir '=https' \
  --silent \
  --show-error \
  --url "$source_url" \
  --output "$tmp_csv"
then
  die "CSV download failed after bounded retries"
fi

if [[ ! -s "$tmp_csv" ]]; then
  die "downloaded CSV is empty"
fi

if ! row_count="$(python - "$tmp_csv" 2>/dev/null <<'PY'
import csv
import sys

path = sys.argv[1]
with open(path, newline="", encoding="utf-8-sig") as source:
    reader = csv.reader(source, strict=True)
    try:
        header = next(reader)
    except StopIteration:
        raise SystemExit("CSV has no header")
    if not header or any(not column.strip() for column in header):
        raise SystemExit("CSV header is empty or contains a blank column")
    if len(set(header)) != len(header):
        raise SystemExit("CSV header contains duplicate columns")

    count = 0
    for row in reader:
        if not row or all(not value.strip() for value in row):
            raise SystemExit("CSV contains a blank data record")
        if len(row) != len(header):
            raise SystemExit("CSV row width differs from its header")
        count += 1
    if count == 0:
        raise SystemExit("CSV contains no data rows")
    print(count)
PY
)"; then
  die "downloaded content is not a non-empty, consistent CSV"
fi

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum < "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 < "$1" | awk '{print $1}'
  else
    die "sha256sum or shasum is required"
  fi
}

sha256_text() {
  if command -v sha256sum >/dev/null 2>&1; then
    printf '%s' "$1" | sha256sum | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
  else
    die "sha256sum or shasum is required"
  fi
}

file_size() {
  wc -c < "$1" | tr -d '[:space:]'
}

csv_sha256="$(sha256_file "$tmp_csv")"
csv_size_bytes="$(file_size "$tmp_csv")"
gzip -n -c "$tmp_csv" > "$tmp_gzip"
gzip -t "$tmp_gzip"
gzip_sha256="$(sha256_file "$tmp_gzip")"
gzip_size_bytes="$(file_size "$tmp_gzip")"
record_id="$(sha256_text "$(printf '%s\n%s' "$source_url" "$csv_sha256")")"

gzip_name="weather-$record_id.csv.gz"
manifest_name="weather-$record_id.manifest.json"
gzip_path="$partition_dir/$gzip_name"
manifest_path="$partition_dir/$manifest_name"
recorded_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python - "$tmp_manifest" "$source_url" "$partition_date" "$PARTITION_TIMEZONE" \
  "$recorded_at_utc" "$row_count" "$csv_sha256" "$csv_size_bytes" \
  "$gzip_name" "$gzip_sha256" "$gzip_size_bytes" "$record_id" <<'PY'
import json
import sys

(
    destination, source_url, partition_date, timezone, recorded_at,
    row_count, csv_sha256, csv_bytes, gzip_name, gzip_sha256, gzip_bytes,
    record_id,
) = sys.argv[1:]
manifest = {
    "schema_version": "dataforge.week1.csv-ingest.v1",
    "status": "COMPLETE",
    "record_id": record_id,
    "source_url": source_url,
    "partition_date": partition_date,
    "partition_timezone": timezone,
    "recorded_at_utc": recorded_at,
    "row_count_excluding_header": int(row_count),
    "csv_sha256": csv_sha256,
    "csv_size_bytes": int(csv_bytes),
    "gzip_file": gzip_name,
    "gzip_sha256": gzip_sha256,
    "gzip_size_bytes": int(gzip_bytes),
}
with open(destination, "w", encoding="utf-8", newline="\n") as target:
    json.dump(manifest, target, ensure_ascii=True, sort_keys=True, indent=2)
    target.write("\n")
PY

verify_existing() {
  [[ -f "$gzip_path" && -f "$manifest_path" ]] || return 1
  gzip -t "$gzip_path" || return 1
  [[ "$(sha256_file "$gzip_path")" == "$gzip_sha256" ]] || return 1
  [[ "$(file_size "$gzip_path")" == "$gzip_size_bytes" ]] || return 1
  python - "$manifest_path" "$source_url" "$partition_date" "$PARTITION_TIMEZONE" \
    "$row_count" "$csv_sha256" "$csv_size_bytes" "$gzip_name" \
    "$gzip_sha256" "$gzip_size_bytes" "$record_id" <<'PY'
import json
import sys

(
    path, source_url, partition_date, timezone, row_count, csv_sha256,
    csv_bytes, gzip_name, gzip_sha256, gzip_bytes, record_id,
) = sys.argv[1:]
with open(path, encoding="utf-8") as source:
    actual = json.load(source)
expected = {
    "schema_version": "dataforge.week1.csv-ingest.v1",
    "status": "COMPLETE",
    "record_id": record_id,
    "source_url": source_url,
    "partition_date": partition_date,
    "partition_timezone": timezone,
    "row_count_excluding_header": int(row_count),
    "csv_sha256": csv_sha256,
    "csv_size_bytes": int(csv_bytes),
    "gzip_file": gzip_name,
    "gzip_sha256": gzip_sha256,
    "gzip_size_bytes": int(gzip_bytes),
}
if any(actual.get(key) != value for key, value in expected.items()):
    raise SystemExit(1)
PY
}

if [[ -e "$gzip_path" || -e "$manifest_path" ]]; then
  if verify_existing; then
    printf 'NOOP: verified existing partition %s (%s rows, sha256 %s)\n' \
      "$partition_date" "$row_count" "$csv_sha256"
    exit 0
  fi
  die "a prior artifact is incomplete or does not match; no existing file was replaced"
fi

publish_without_replace() {
  local source="$1"
  local destination="$2"
  if ! (set -o noclobber; : > "$destination") 2>/dev/null; then
    return 1
  fi
  mv "$source" "$destination"
}

# The manifest is the completion marker and is atomically published last.
publish_without_replace "$tmp_gzip" "$gzip_path" ||
  die "artifact path already exists; no existing file was replaced"
tmp_gzip=""
publish_without_replace "$tmp_manifest" "$manifest_path" ||
  die "manifest path already exists; inspect the incomplete artifact before retrying"
tmp_manifest=""

printf 'PASS: %s rows; CSV sha256 %s; %s bytes; gzip %s bytes; %s\n' \
  "$row_count" "$csv_sha256" "$csv_size_bytes" "$gzip_size_bytes" "$gzip_path"
