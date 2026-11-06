# Data provenance and license gates

## First-party synthetic fixtures

`dataforge generate` creates deterministic synthetic commerce tables for a fictional retailer, with fictional identifiers and transactions. These are demo/test fixtures, not observations from an actual retailer. The generator marks the dataset as `synthetic` and records the seed and source-file hashes in `_DATAFORGE_SOURCE.json`.

The generator also creates deterministic synthetic daily weather with `source="synthetic"`. Do not describe these values as weather observations or use them to support real-world weather claims.

P6 adds a write guard: an existing source set can be regenerated only when its marker explicitly identifies a synthetic dataset and each existing CSV matches its recorded SHA-256. Manual, modified, malformed-marker, or externally overridden data fails before files are written. Use the archive-first reset in [`operations_runbook.md`](operations_runbook.md) if a synthetic reset is needed; do not overwrite an API or user-supplied source folder.

## Optional Open-Meteo weather

`dataforge weather-fetch` makes an explicit HTTP request to the Open-Meteo Historical Weather API; it does not run during ordinary generation or ingestion. The current adapter requests ERA5 daily precipitation and maximum temperature for approximate city-centre coordinates for HCM, HN and DN, uses `Asia/Ho_Chi_Minh`, and labels returned rows `source="open_meteo_era5"`. These coordinates represent coarse province-level proxies, not shipment routes or precise local observations. Weather/shipment comparisons are correlational and must not be presented as causal.

The adapter requires every requested province response to contain the exact ordered inclusive daily date range. Missing, duplicate, extra, shuffled or out-of-range dates are rejected before CSV, marker or provenance writes. Ingestion checks that the `weather_daily.csv` SHA-256 and row count agree with both `_DATAFORGE_SOURCE.json` and the complete `weather_provenance.json` sidecar before promoting an active run. Fetch stages all outputs, promotes the CSV last and restores the prior files on caught write failures. If the process is interrupted, a hash/presence manifest and prior files remain under `.open_meteo/transactions/{transaction_id}/`; ingestion fails closed until the prior set is restored or an explicitly requested fetch repairs it. P6 verification used mocks and did not make a live weather request.

Open-Meteo's public terms and licence pages were reviewed on **2026-11-05**. At that review, the free API was limited to non-commercial use and API data was offered under CC BY 4.0; attribution should link to Open-Meteo and identify changes. Re-check the current terms before publishing or using data commercially because terms can change. See the [Historical Weather API documentation](https://open-meteo.com/en/docs/historical-weather-api), [Terms of Use](https://open-meteo.com/en/terms), and [licence conditions](https://open-meteo.com/en/licence).

P5 live smoke on **2026-11-03** made one real request for HCM (10.8231, 106.6297), 2022-01-01 through 2022-01-02, daily precipitation and maximum temperature, `Asia/Ho_Chi_Minh`, ERA5. The API returned HTTP 200 and two daily rows; both passed the weather schema and produced a Parquet file in an isolated temporary directory. The raw JSON response was retained locally and its SHA-256 matched the provenance sidecar. This was an educational, non-commercial smoke test; neither the raw response nor local run receipts are included in the portfolio package.

## Third-party IVin Datathon dataset — gated, not integrated

The [IVin Datathon 2026 Round 1 public repository](https://github.com/vin-datathon-2026/round1) was inspected on **2026-11-03**. Its visible root file list and README describe 13 relational tables for simulated Vietnamese fashion e-commerce activity, including historical data described as 2012–2022. The README presents Revenue and COGS targets, but this does not establish that the data is a company's observed retail history.

No license statement was visible in the reviewed root file list or README. Redistribution and reuse rights therefore remain **unverified**. No raw dataset files were downloaded or added to this workspace; dataset headers, row counts, null patterns, keys and business rules have not been independently profiled locally. Do not integrate or redistribute these files until their license and schema are verified. Keep any later approved local copy under `data/external/`, outside source-controlled fixtures, and record the mapping and provenance before building an adapter.

## Handling rules

- Preserve the distinction between `synthetic` fixtures and `open_meteo_era5` API observations in source markers, manifests, tables and report labels. Do not mix the labels or make observational business claims from the synthetic values.
- Third-party source data remains separate from the baseline fixtures; no adapter or Datathon-derived business metric is currently claimed.
- `.env`, credentials, PII, personal customer exports and raw third-party CSVs must not be committed.
