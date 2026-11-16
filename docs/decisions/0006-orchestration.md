# 0006. Orchestration with Airflow, Astro Runtime and Cosmos

- **Status:** Accepted
- **Date:** 2026-11-14

## Context

The pipeline runs one GA4 day at a time: extract from BigQuery, load to
Snowflake, reconcile row counts, then build and test dbt. It must backfill all
92 days safely, rerun any failed day, and keep credentials off the image.

## Decision

- **Astro Runtime 3.3-12 (Airflow 3.3.2) on Python 3.12, run with the Astro
  CLI.** Airflow 3.4.0 was eight days old and not yet in an Astro Runtime, and
  Cosmos 1.16.0 tests Airflow 3.4 only as beta.
- **Cosmos 1.16.0** renders the dbt project as one task per model with
  `TestBehavior.BUILD`, so each model runs with its tests and a failure
  points at one model. dbt signs in with
  `SnowflakeEncryptedPrivateKeyFilePemProfileMapping`, the same key pair as
  on the Mac, and runs the `prod` target.
- **Separate virtual environments.** Airflow's constraints pin older versions
  of pyarrow, the BigQuery client and the Snowflake connector. dbt runs from
  `dbt_venv` (subprocess invocation) and extract, load and reconcile run from
  `el_venv` with `@task.external_python`, both with the project's own pinned
  versions. A test keeps the image pins equal to `pyproject.toml`.
- **Explicit daily data intervals** (`CronDataIntervalTimetable`, UTC): the
  run for a day covers exactly that GA4 day, matching the sample's UTC day
  boundary. Catchup is on and `max_active_runs` is 1, so turning the DAG on
  backfills the 92 days in order.
- **Retries with exponential backoff** on every task (two retries, up to 20
  minutes apart), and a one-hour timeout per task.
- **No secrets in the image.** Keys and Google credentials are mounted
  read-only; settings come from a gitignored `orchestration/.env` written
  with owner-only permissions by `make airflow-env`.
- **dbt packages from the host.** `make airflow-start` runs `dbt deps` first
  and Cosmos copies the installed packages, so tasks do not download them on
  every run.

## Alternatives considered

- **Airflow 3.4.0.** Newer, but no Astro Runtime yet and only beta Cosmos
  support.
- **Installing everything into Airflow's environment.** Simpler, but it would
  downgrade the project's libraries to Airflow's constraints or risk breaking
  Airflow.
- **A single `dbt build` task.** Fewer tasks, but a failure would not show
  which model failed, and the graph would not show lineage.
- **The default cron timetable in Airflow 3.** It has no data intervals; an
  explicit interval timetable makes the processed day unambiguous.

## Consequences

- Every task is idempotent: rerunning a day or backfilling a range gives the
  same result.
- DAG integrity tests run both inside the image (`astro dev pytest`) and in CI
  without Docker (`make dag-test`).
- The full backfill rebuilds the marts once per day, which costs a few credits;
  the credit cap bounds it.
