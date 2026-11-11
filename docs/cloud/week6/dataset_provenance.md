# Week 6 dataset provenance and reproducibility

**Source page reviewed:** 2026-11-10 (Asia/Bangkok)
**Dataset:** NYC TLC Yellow Taxi monthly trip records, January–April 2024, plus the official Taxi Zone lookup CSV
**Use:** isolated local Spark lab only; raw source files are kept outside the Git checkout.

## Official sources and terms

The [NYC TLC Trip Record Data page](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) links each selected Yellow Taxi Parquet file and the [Taxi Zone Lookup Table](https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv). The month URLs are:

| Period | Direct TLC URL |
|---|---|
| 2024-01 | `https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-01.parquet` |
| 2024-02 | `https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-02.parquet` |
| 2024-03 | `https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-03.parquet` |
| 2024-04 | `https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2024-04.parquet` |
| Taxi zones | `https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv` |

The [Yellow Trips Data Dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf) defines pickup/drop-off times as meter engagement/disengagement, the pickup/drop-off Location IDs as Taxi Zones, `trip_distance` in taximeter-reported miles, and `total_amount` as the amount charged excluding cash tips. TLC says these records are submitted by authorized technology providers under TPEP/LPEP and that TLC does not guarantee record accuracy. The TLC page warns that schemas can change and says `cbd_congestion_fee` was added for 2025 data onward.

**License/redistribution:** the [NYC Open Data FAQ](https://www.nyc.gov/opendata/get-started/FAQs) says there are no restrictions on use of Open Data. The files used here are linked from the TLC data page, which does not identify a separate named license; the [City's Terms of Use](https://www.nyc.gov/main/terms-of-use) and any applicable data-provider terms still matter. No named license is asserted. Credit NYC TLC / City of New York, keep the accuracy caveat, and re-check current terms before redistributing raw files. Source data is not checked into this repository.

## Acquired-file receipt

The lead acquired the files from the official links and captured local byte, SHA-256, and Parquet footer receipts. PySpark read the four files together and materialized **13,069,067 rows**, exactly matching the sum of the four footer row counts. Per-file values below are Parquet footer counts; the Spark confirmation was for the combined selection.

| Source | Bytes | SHA-256 | Footer rows | Row groups | Receipt status |
|---|---:|---|---:|---:|---|
| `yellow_tripdata_2024-01.parquet` | 49,961,641 | `c4d59da7bbc8abaeeeb1727947ee93d9891a71acb42854bd80db1571b2030510` | 2,964,624 | 3 | `ACQUIRED; FOOTER_RECONCILED` |
| `yellow_tripdata_2024-02.parquet` | 50,349,284 | `c76c43c18c6c6664080dd920baab4928988d5786a6b65980792ca7cd796f9f20` | 3,007,526 | 3 | `ACQUIRED; FOOTER_RECONCILED` |
| `yellow_tripdata_2024-03.parquet` | 60,078,280 | `2d4cdc8fb96726cdd3803b13b02d2e61e71d45720aff0ebc693a8bdd1f249823` | 3,582,628 | 4 | `ACQUIRED; FOOTER_RECONCILED` |
| `yellow_tripdata_2024-04.parquet` | 59,133,625 | `ce37f736c7cf9e92164c850ef2b502a8f7bb590fc1804b6edbcb80293da01b89` | 3,514,289 | 4 | `ACQUIRED; FOOTER_RECONCILED` |
| `taxi_zone_lookup.csv` | 12,331 | `1a99e105092230f8620f301edcca7f80d3080642ff404d28ed957d3fa222c8ed` | 265 CSV records | N/A | `ACQUIRED; SPARK_VALIDATED` |
| **Yellow Taxi total** | **220,522,830** | N/A | **13,069,067** | **14 total** | `SPARK_COUNT_VERIFIED; FOOTERS_MATCH` |

**Spark materialization:** run `week6-20261110-03`, Spark application `local-1794329076657`, runtime Spark 3.5.9. The total input count matched the Parquet metadata. The four files were schema-checked individually and had identical schemas.

**Exact raw-file schema:** lead's PyArrow footer inspection found the same schema in all four files, with no 2025 `cbd_congestion_fee` field. It contains these 19 fields and Arrow types:

| Field | Arrow type |
|---|---|
| `VendorID` | `int32` |
| `tpep_pickup_datetime`, `tpep_dropoff_datetime` | `timestamp[us]` |
| `passenger_count`, `RatecodeID`, `payment_type` | `int64` |
| `trip_distance`, `fare_amount`, `extra`, `mta_tax`, `tip_amount`, `tolls_amount`, `improvement_surcharge`, `total_amount`, `congestion_surcharge`, `Airport_fee` | `double` |
| `PULocationID`, `DOLocationID` | `int32` |
| `store_and_fwd_flag` | `large_string` |

The official lookup has 265 rows and 265 unique IDs, with all assigned IDs 1–263 present. IDs 264 and 265 are unassigned/out of scope (Unknown or Outside of NYC) and are rejected. Spark validated 263 unique assigned rows before joining. The CSV columns are `LocationID`, `Borough`, `Zone`, and `service_zone`; the four null cells are one in `Borough`, one in `Zone`, and two in `service_zone`, all on the unassigned rows. The dictionary is a field reference; the table records the actual Parquet logical schema observed by PyArrow and Spark.

## Timestamp coverage and quality profile

The published timestamps are timezone-naive meter wall-clock values. A PyArrow streaming scan observed these raw minimum and maximum values; they are not UTC instants:

| File | Pickup minimum | Pickup maximum | Dropoff minimum | Dropoff maximum | Null pickup/dropoff timestamps |
|---|---|---|---|---|---:|
| 2024-01 | `2002-12-31 22:59:39` | `2024-02-01 00:01:15` | `2002-12-31 23:05:41` | `2024-02-02 13:56:52` | 0 / 0 |
| 2024-02 | `2008-12-31 22:52:49` | `2024-03-01 00:01:37` | `2008-12-31 23:04:09` | `2024-03-01 23:24:42` | 0 / 0 |
| 2024-03 | `2002-12-31 22:17:10` | `2024-04-01 00:34:55` | `2002-12-31 22:42:24` | `2024-04-02 18:08:46` | 0 / 0 |
| 2024-04 | `2002-12-31 22:10:04` | `2024-05-01 00:02:36` | `2002-12-31 22:14:22` | `2024-05-01 23:22:35` | 0 / 0 |

The 2024 Yellow Taxi files contain 13,069,067 rows. Under the explicit policy, 12,686,794 were accepted and 382,273 rejected; `accepted + rejected = input` passed. Exclusive first-rejection reasons were:

| First rejection reason | Rows |
|---|---:|
| Unknown/unassigned pickup or dropoff zone | 128,332 |
| Nonpositive trip distance | 248,798 |
| Invalid duration (nonpositive or over 24 hours) | 3,963 |
| DST gap/fold or trip interval crossing a UTC-offset change | 1,156 |
| Pickup outside `[2024-01-01, 2024-05-01)` | 24 |
| **Total rejected** | **382,273** |

There were no null critical fields, invalid timestamp parses, nonfinite required distance/money values, or decimal-range violations. Five optional source fields have 1,160,538 nulls each (`passenger_count`, `RatecodeID`, `store_and_fwd_flag`, `congestion_surcharge`, and `Airport_fee`); they do not determine acceptance. The full-row fingerprint flagged one duplicate-like extra row, but no rows were removed because equal source rows are not a trustworthy trip identity.

Negative money and adjustment values were flagged and retained. The row-level review flag covered 194,695 records. Per-field negative counts are diagnostic and can overlap:

| Field | Negative rows |
|---|---:|
| `fare_amount` | 194,135 |
| `total_amount` | 159,644 |
| `improvement_surcharge` | 159,633 |
| `congestion_surcharge` | 130,503 |
| `extra` | 79,936 |
| `Airport_fee` | 23,252 |
| `tolls_amount` | 10,948 |
| `mta_tax` | 154,706 |
| `tip_amount` | 483 |

## Re-download and verification

The downloader uses the official monthly URL pattern above, writes to a scratch directory (default `%TEMP%\dataforge-spark-nyc-taxi` on Windows), streams each response to a `.partial` file, checks transfer length when advertised, hashes the completed bytes, and renames it into place atomically. Existing files are re-hashed against the prior local manifest; a mismatch fails instead of silently reusing or replacing the source. Use `--refresh` only to explicitly replace an existing acquisition after a full new download succeeds.

```powershell
python .\labs\spark_nyc_taxi\download.py `
  --data-dir "$env:TEMP\dataforge-spark-nyc-taxi" `
  --months 1 2 3 4
```

The generated `source_manifest.json` records each URL, local path, byte count, SHA-256, transfer status and `row_count: NOT_RUN`. Spark must separately count the files and update a run receipt; do not replace footer counts with invented materialized counts. For a different scratch mount, pass `--data-dir` or set `DATAFORGE_SPARK_DATA_DIR`.

## Schema and time interpretation

The Yellow Taxi schema fields needed by the lab are `tpep_pickup_datetime`, `tpep_dropoff_datetime`, `PULocationID`, `DOLocationID`, `trip_distance`, `fare_amount`, and `total_amount`. The observed files share the 19-field schema above; no 2025+ congestion fee is imputed into these 2024 files. Zone enrichment is a many-to-one lookup on `LocationID`; verify key uniqueness before joining. IDs 264/265 or other missing/unassigned IDs are treated as unknown and rejected. Do not deduplicate: TLC does not provide a guaranteed stable trip ID, and identical-looking trips can be real trips.

The TLC trip-time fields have no UTC offset in the published schema and describe meter times in NYC local time. The lab treats them as local wall-clock values in `America/New_York`; pickup must fall inside `[2024-01-01, 2024-05-01)`. A valid drop-off may cross a month boundary if duration remains positive and no more than 24 hours. Reject invalid/nonexistent or ambiguous local times and trips whose endpoints straddle a DST offset change because the raw file does not disambiguate the exact instant. Report any negative fare, surcharge, or total amount as a review flag and keep it in the accepted monetary sums; a negative amount may represent an adjustment or credit and is not automatically discarded.

## Re-download and rerun status

The acquisition manifest under ignored local scratch retains all five file hashes. The full Spark materialization and source-quality profile above are `LOCAL_TESTED`. The files are kept under `labs/spark_nyc_taxi/data/raw/` locally and are not committed.
