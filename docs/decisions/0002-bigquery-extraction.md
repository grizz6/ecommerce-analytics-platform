# 0002. BigQuery extraction approach

- **Status:** Accepted
- **Date:** 2026-11-06

## Context

The GA4 sample lives in 92 daily tables, `events_20201101` to
`events_20210131`, confirmed with a metadata-only listing. Extraction runs in
the BigQuery sandbox, which has a free monthly query allowance and no billing
account. Nothing may create a charge, and every day must be re-extractable
without leaving duplicates or partial files.

## Decision

- **One query per day on the wildcard table**, filtered with
  `_TABLE_SUFFIX = 'YYYYMMDD'`. The suffix is written into the SQL as a
  constant, formatted from a date object, so BigQuery prunes the scan to one
  daily table and the dry-run estimate is accurate.
- **Explicit column list.** Only the 17 top-level columns the models need are
  selected. Unused columns (`privacy_info`, `user_ltv`, `app_info`,
  `stream_id`, `event_dimensions`, `event_server_timestamp_offset`) are left
  out to reduce bytes processed.
- **Plan, then extract.** Every requested day is dry-run first. The run stops
  before any real query if one day exceeds the per-query limit or the total
  exceeds the per-run limit. Each real query also sets
  `maximum_bytes_billed`, so BigQuery enforces the limit independently.
- **Standard API for results, not the Storage Read API.** The Storage Read
  API is billed separately. Daily result sets are small enough for the
  standard API.
- **Nested fields stay nested.** Results are cast to one Arrow schema shared
  with the synthetic fixtures, and written as Parquet with nested structs and
  lists intact.
- **Atomic, idempotent writes.** Each day is written to a temporary file and
  renamed over `event_date=YYYYMMDD/part-0.parquet`. A rerun replaces the day.
- **Manifest for reconciliation.** `_manifest.json` records rows, bytes and a
  file checksum per day. It is gitignored with the data and is the source of
  truth for row-count reconciliation after loading to Snowflake.

## Alternatives considered

- **Querying each `events_YYYYMMDD` table by name.** Equally cheap, but the
  wildcard with `_TABLE_SUFFIX` is the documented pattern for sharded GA4
  exports and extends naturally to range queries.
- **A query parameter for the suffix.** Safer in general, but a constant
  filter is what guarantees table pruning. The value can only be eight digits
  produced from a date, so it cannot carry injected SQL.
- **Exporting to Cloud Storage.** Needs a bucket, which needs billing.

## Consequences

- Dry runs make cost visible before anything runs, and the limits can be
  tuned in `.env` without code changes.
- The schema is fixed to the obfuscated sample, including its INTEGER-typed
  placeholder fields. A schema change in the source makes the cast fail
  loudly instead of writing mismatched files.
