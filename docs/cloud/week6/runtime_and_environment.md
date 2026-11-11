# Week 6 Spark runtime and environment

## Pinned compatibility matrix

| Layer | Pin | Compatibility evidence |
|---|---|---|
| Container Python | `3.11.18` (`python:3.11.18-slim-bookworm`, pinned image digest in `Dockerfile`) | Python 3.11 is within Spark 3.5's documented Python 3.8+ range. |
| Java and timezone data | OpenJDK 17 JRE and `tzdata` from the Bookworm package repository | Apache Spark 3.5.9 documents Java 17 as a supported runtime. Exact Debian package builds are captured from the built image at execution time. |
| Apache Spark / PySpark | `3.5.9` | Spark's 3.5.9 release is a maintenance release for the 3.5 line. |
| Delta Lake | `3.3.3` | Delta's official compatibility matrix lists Delta 3.3.x with Spark 3.5.x. |
| Delta JVM artifact | `io.delta:delta-spark_2.12:3.3.3` | The Delta PyPI helper resolves the matching Scala 2.12 artifact for Spark 3.5. |
| PyArrow | `23.0.1` | Reads one bounded source-date partition for the independent Decimal oracle; no full source file is collected to the driver. |
| pytest | `9.2.0` | Runs the deterministic network-free lab fixture suite inside the same image. |

Primary references: [Spark 3.5.9 overview](https://spark.apache.org/docs/3.5.9/), [Spark 3.5.9 release](https://spark.apache.org/releases/spark-release-3-5-9.html), [Delta Lake release compatibility matrix](https://docs.delta.io/releases/), [Python 3.11.18 release](https://www.python.org/downloads/release/python-31118/).

The workload uses Linux Spark inside Docker Desktop on Windows; it does not rely on native Windows Hadoop binaries or the host's Java 23 / Python 3.13.9. Docker currently exposes 20 CPUs and 7.6 GiB to containers. Compose limits this lab to 4 CPUs and 6 GiB so it leaves headroom for Windows and Docker. Host and Docker observations were recorded on 2026-11-10; they describe this machine, not a general performance guarantee.

## Reproducible commands

From the repository root:

```powershell
docker compose --file labs/spark_nyc_taxi/compose.yaml build
docker compose --file labs/spark_nyc_taxi/compose.yaml run --rm spark --version
docker compose --file labs/spark_nyc_taxi/compose.yaml run --rm spark -c "import sys, pyspark; print(sys.version); print(pyspark.__version__)"
.\labs\spark_nyc_taxi\ci.ps1
```

The image pins the Python base image by patch tag and digest, as well as PySpark, Delta, PyArrow, and pytest package versions. OpenJDK 17 and IANA timezone data are installed from the Debian Bookworm security repository at image build time; record `java -version` and the Debian package versions from the built image in the execution receipt. Delta's Spark JAR is resolved by the pinned Delta helper on the first Delta-enabled session, so that first start needs Maven Central access. Spark UI is served at `http://localhost:4040` while the application is running when Docker's host port forwarding is available.

The session factory in `labs/spark_nyc_taxi/spark_session.py` fixes the Spark SQL session timezone to `America/New_York`, enables Parquet inference of timezone-naive timestamps, enables local event logging, and disables automatic broadcast selection. Both benchmark candidates use the same AQE and shuffle-partition settings; only the candidate has an explicit broadcast hint.

## Runtime smoke receipt

**`LOCAL_TESTED` — 2026-11-10.** The Docker build and a synthetic two-row Delta transaction smoke completed with exit code 0. The smoke imported the shared session factory, ran the Delta create/append/replay/history/version-0 read path, and did not download TLC data.

| Component | Observed value |
|---|---|
| Python | `3.11.18` |
| PySpark / Spark | `3.5.9` / `3.5.9` |
| Delta Python / JVM artifact | `3.3.3` / `io.delta:delta-spark_2.12:3.3.3` resolved from Maven Central |
| Java | `17.0.21+9-1~deb12u1` |
| IANA timezone data | `2026f-0+deb12u1`; `ZoneInfo('America/New_York')` loaded |
| Spark session timezone | `America/New_York` |
| Docker image | `dataforge-week6-spark:3.5.9` |

The table transaction receipt is recorded in [the Delta demo evidence](table_format_demo.md). This only validates the pinned local runtime and Delta operations on a deterministic synthetic aggregate; it is not evidence of full TLC-scale processing or benchmark performance.

## Full TLC execution receipt

**`LOCAL_MEASURED` — run `week6-20261110-03`, Spark application `local-1794329076657`, executed 2026-11-10/11 (Asia/Bangkok).** Spark read and materialized 13,069,067 rows and matched the sum of all four monthly Parquet footer counts. The quality policy accepted 12,686,794 and rejected 382,273 rows; `accepted + rejected = input` passed. DataFrame and Spark SQL aggregates had zero differing rows.

The output contains 308,833 unique hourly pickup-zone rows with a trip-count sum of 12,686,794. The `pickup_date`-partitioned Parquet output has 121 files / 121 date partitions, 8,330,057 bytes total and 68,843 bytes average. Same-run replay returned `VERIFIED_NO_OP`. A full January 15 partition was independently reconciled using PyArrow row-group reads and a Python/Decimal oracle: 77,033 input rows, 74,680 accepted, 2,353 rejected, 2,089 output groups, exact count/money/distance parity, and maximum p50/p95 difference 0.00034 minutes.

The benchmark compared one warmup and five timed runs per join plan. The baseline median was 213.924 seconds and the broadcast candidate median was 256.307 seconds. Broadcast reduced shuffle write and spill but was 19.8% slower by median; no speedup is claimed. See [the full benchmark receipt](benchmark.md) for ranges, event-log task metrics and caveats.

The Delta demo used 20 rows from the full TLC aggregate at version 0, appended one row at version 1, replayed the same transaction without changing row count/version, inspected metadata/history, and read version 0 back. Its complete receipt is in [table_format_demo.md](table_format_demo.md).

## Scratch data and cleanup

Raw TLC Parquet, zone lookup CSV, normalized rows, Parquet outputs, Delta files, Spark event logs and generated receipts belong under `labs/spark_nyc_taxi/data/` or another explicitly selected scratch directory. They are execution products, not source fixtures. Confirm the repository ignore rule before the first full run. Keep event logs and source files out of commits. The lab never removes or rewrites commerce tables, accepted cloud checkpoints, GCS objects or other phase outputs.

No managed Spark cluster or GCP batch is part of this local runtime. A cloud run would require separate explicit spending approval and its own preflight.
