# 0003. Loading raw events into Snowflake

- **Status:** Accepted
- **Date:** 2026-11-06

## Context

Ninety-two daily Parquet files, 4,295,584 events in total, must be loaded into
`RAW.GA4.EVENTS`. Any day may need to be reloaded, for example after a
re-extract or during an Airflow backfill, and a reload must never create
duplicates or leave a day half loaded. Nested GA4 fields must stay intact for
dbt to flatten later.

## Decision

- **Internal named stage, one folder per day.** Each file is uploaded with
  `PUT ... OVERWRITE = TRUE` to `@RAW.GA4.EVENTS_STAGE/event_date=YYYYMMDD/`,
  so a day's folder only ever holds that day's latest file.
- **Delete and copy in one transaction.** For each day: `BEGIN`, delete the
  day's rows, `COPY INTO` from the day's folder, compare rows loaded with the
  extract manifest, then `COMMIT`, or `ROLLBACK` on any mismatch or error.
- **`FORCE = TRUE`.** Snowflake's load history would otherwise skip a file it
  has seen before. Because the day was just deleted in the same transaction,
  forcing the reload is what makes the operation idempotent.
- **`MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE`.** Parquet columns map to table
  columns by name, not position, and nested structs and lists land in
  `VARIANT` columns.
- **Metadata columns from the file.** `INCLUDE_METADATA` sets `_source_file`
  from `METADATA$FILENAME` and `_loaded_at` from `METADATA$START_SCAN_TIME`,
  so every row records which file and which load produced it.
- **Checksum before upload.** The local file is compared with the SHA-256 in
  the extract manifest before anything is sent, so a damaged or replaced file
  is never loaded.
- **Separate reconciliation.** `reconcile.py` compares per-day counts in
  Snowflake with the manifest and exits non-zero on any difference, so it can
  gate the dbt run in Airflow.

## Alternatives considered

- **`COPY INTO` relying on load history alone.** Prevents duplicates of the
  same file, but cannot replace a day whose file changed, and load history
  expires after 64 days.
- **Load to a staging table, then `MERGE`.** Needs a unique key in the raw
  data, which GA4 does not guarantee (duplicate events exist). Deduplication
  belongs in dbt staging, where it is tested and documented.
- **Snowpipe or external stages.** Built for continuous or cloud-storage
  loads. Neither applies to a static, local dataset, and both add cost or
  infrastructure.

## Consequences

- A rerun of any day is safe and gives the same result.
- A failure on one day leaves that day exactly as it was and stops the run, so
  it is visible immediately.
- Raw rows keep any duplicates present in the source. dbt staging is
  responsible for deduplication.
