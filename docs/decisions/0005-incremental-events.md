# 0005. Incremental strategy for staged events

- **Status:** Accepted
- **Date:** 2026-11-11

## Context

`stg_ga4__events` is the largest model (about 4.3 million rows) and is rebuilt
on every orchestrated run. Any day can be reloaded into RAW, for example during
an Airflow backfill, and the raw data contains exact duplicate events.

## Decision

- **Snowflake: incremental, merge on `event_key`.** Each run selects raw rows
  whose `event_date` is on or after the latest staged date minus
  `var('event_lookback_days')` (3), deduplicates them, and merges on
  `event_key`. Reloaded days update their existing rows instead of adding
  copies, and the lookback covers late or reloaded days.
- **DuckDB: table.** The CI fixtures are small, so a full rebuild is simpler
  and always correct.
- **Deterministic keys and deduplication.** `event_key` fingerprints user,
  timestamp, event name, bundle sequence and all event parameters. Rows with
  the same key are exact duplicates; one is kept by ordering on `_loaded_at`
  and `_source_file`, so the choice is repeatable.

## Alternatives considered

- **Full rebuild on Snowflake.** Simple, but reprocesses every row on every
  run. Fine at this size, and still available with `dbt build --full-refresh`.
- **Append-only incremental.** Cheaper per run, but a reloaded day would be
  inserted twice.
- **Delete+insert by date.** Also idempotent, but merge on the event key also
  protects against duplicates arriving in a later load.

## Consequences

- A full refresh and an incremental run give the same result.
- Changing the key definition requires `--full-refresh` on Snowflake.
