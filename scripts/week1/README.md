# Week 1 public CSV shell exercise

The syllabus asks for a shell script that fetches a public CSV, counts data rows,
compresses it, stores it by date, and is delivered through a pull request. The
exercise is implemented in [week1_fetch_csv.sh](../week1_fetch_csv.sh).

## Run it

From the repository root in Git Bash, WSL, or Linux:

~~~bash
bash scripts/week1_fetch_csv.sh
~~~

The default source is the Seattle weather CSV in Vega Datasets 3.3.1. The
[dataset catalog](https://vega.github.io/vega-datasets/datasets/seattle_weather/)
attributes it to NOAA National Climatic Data Center and labels the source data
public domain. The CSV is a curated teaching dataset; its weather category is
synthesized from source fields. The catalog's dataset-level license metadata is
separate from the repository code license, so check the original source terms
before redistributing it. The output goes under
.local/week1/YYYY-MM-DD/; the partition date uses Asia/Bangkok.

To use another public CSV or repeat a known observation date:

~~~bash
bash scripts/week1_fetch_csv.sh \
  --url 'https://example.org/public/sample.csv' \
  --output-dir '.local/week1' \
  --date 2026-11-13
~~~

The script requires HTTPS, disallows URL credentials, query strings, and
fragments, limits downloads to 10 MiB, retries transient curl errors twice,
validates the CSV header and every record, and writes a gzip archive plus JSON
provenance manifest. The manifest records the source URL, partition timezone,
UTC capture time, row count excluding the header, CSV and gzip byte sizes, and
SHA-256 hashes.

Names include a digest of the source URL and CSV bytes. Identical content from
the same URL and date becomes a verified no-op; changed content receives a new
immutable name. Temporary files are created beside the final artifacts and
renamed atomically. The manifest is published last as the completion marker.
The default .local/ directory is git-ignored.

## Shell concepts

- grep searches output or logs for a status.
- awk extracts fields from command output; this script uses it to select a
  checksum from sha256sum.
- sed can transform text, but avoid using it to rewrite CSV because quoted
  fields can contain commas or newlines.
- wc -c records exact file size in bytes.
- gzip -n compresses without embedding a machine-specific filename or time.
- curl --fail --location downloads over HTTPS; bounded retries and timeouts
  prevent a failed source from hanging a run.

The same Bash script works in Git Bash, WSL, and Linux. PowerShell has different
quoting, pipelines, and error handling; use bash scripts/week1_fetch_csv.sh
from PowerShell when Git Bash is installed, or run it inside WSL.

## Cron example only

This example runs at 09:00 every day in the user's crontab timezone. It is
documentation only; the exercise does not install or enable a cron job.

~~~cron
0 9 * * * cd /path/to/DataForge && /usr/bin/bash scripts/week1_fetch_csv.sh
~~~

Offline fixture tests use only a loopback HTTP server and never contact the
public source.
