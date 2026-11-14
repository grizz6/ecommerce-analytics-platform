"""Entry points the Airflow DAG calls for one day: extract, load and reconcile.

Each function takes the day as YYYY-MM-DD text (Airflow renders it from the
run's data interval), does the whole step, and returns a small summary of
counts that Airflow keeps as the task's result. Any problem raises, so the
task fails and Airflow retries it. Every step is idempotent, so retries and
backfills are safe.

Settings come from environment variables, exactly as on the command line.
Nothing here imports Airflow, so it is tested in CI without it.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from extract_load import bigquery_extract, reconcile, snowflake_load
from extract_load.config import ExtractSettings
from extract_load.ga4_schema import EVENT_DATE_FORMAT
from extract_load.logging_utils import configure_logging
from extract_load.snowflake_client import SnowflakeSettings, connect

logger = logging.getLogger(__name__)


class PipelineStepError(RuntimeError):
    """Raised when a step finishes but its result is not acceptable."""


def _parse_day(day: str) -> date:
    # strptime, not date.fromisoformat: since Python 3.11 fromisoformat also
    # accepts the compact 20201101 form, and only YYYY-MM-DD is expected here.
    try:
        return datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).date()
    except ValueError as exc:
        msg = f"day must be YYYY-MM-DD, got {day!r}"
        raise PipelineStepError(msg) from exc


def run_extract(day: str) -> dict[str, Any]:
    """Extract one day from BigQuery to Parquet, within the configured byte limits."""
    configure_logging()
    settings = ExtractSettings.from_env()
    results = bigquery_extract.run(
        bigquery_extract.create_client(settings), settings, [_parse_day(day)]
    )
    result = results[0]
    return {
        "event_date": result.event_date,
        "rows": result.rows,
        "bytes_processed": result.bytes_processed,
    }


def run_load(day: str) -> dict[str, Any]:
    """Load one extracted day into RAW.GA4.EVENTS, replacing any earlier load."""
    configure_logging()
    parsed = _parse_day(day)
    raw_dir = ExtractSettings.from_env().raw_data_dir
    entries = snowflake_load.select_days(bigquery_extract.load_manifest(raw_dir), parsed, parsed)
    settings = SnowflakeSettings.for_loader()
    connection = connect(settings)
    try:
        result = snowflake_load.run(connection, settings, raw_dir, entries)[0]
    finally:
        connection.close()
    return {"event_date": result.event_date, "rows_loaded": result.rows_loaded}


def run_reconcile(day: str) -> dict[str, Any]:
    """Check that the day, and every other extracted day, matches in Snowflake."""
    configure_logging()
    event_date = _parse_day(day).strftime(EVENT_DATE_FORMAT)
    manifest = bigquery_extract.load_manifest(ExtractSettings.from_env().raw_data_dir)
    settings = SnowflakeSettings.for_loader()
    connection = connect(settings)
    try:
        loaded = reconcile.fetch_counts(connection, settings)
    finally:
        connection.close()
    expected = {key: entry["rows"] for key, entry in manifest.items()}
    result = reconcile.compare(expected, loaded)
    reconcile.report(result)
    if event_date not in result.matched:
        msg = f"{event_date} does not match between the manifest and Snowflake"
        raise PipelineStepError(msg)
    if not result.ok:
        msg = "Row counts differ between the manifest and Snowflake; see the task log"
        raise PipelineStepError(msg)
    return {
        "event_date": event_date,
        "rows": expected[event_date],
        "days_matched": len(result.matched),
        "total_rows": result.loaded_rows,
    }
