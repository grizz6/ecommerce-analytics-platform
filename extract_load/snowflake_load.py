"""Load extracted GA4 Parquet files into RAW.GA4.EVENTS in Snowflake.

Each day is loaded idempotently, in one transaction:

1. Verify the local file against the checksum in the extract manifest.
2. PUT the file to its own stage folder, event_date=YYYYMMDD/, replacing any
   earlier copy.
3. BEGIN; delete that day's rows; COPY INTO the table with
   MATCH_BY_COLUMN_NAME, adding _source_file and _loaded_at from file
   metadata. FORCE = TRUE reloads the file even if Snowflake's load history
   says it was loaded before, because the delete has just removed those rows.
4. COMMIT only if the rows loaded equal the rows in the manifest; otherwise
   ROLLBACK, which leaves the day exactly as it was before the run.

Rerunning a day therefore replaces it without duplicates, and a failed day
never leaves partial data behind.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from extract_load.bigquery_extract import date_range, load_manifest
from extract_load.config import ConfigError, ExtractSettings
from extract_load.ga4_schema import EVENT_DATE_FORMAT, partition_path
from extract_load.logging_utils import configure_logging
from extract_load.snowflake_client import (
    Connection,
    Cursor,
    SnowflakeError,
    SnowflakeSettings,
    column_index,
    connect,
    describe_driver_error,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadResult:
    """The outcome of loading one day."""

    event_date: str
    rows_expected: int
    rows_loaded: int


def stage_folder(settings: SnowflakeSettings, event_date: str) -> str:
    return f"{settings.events_stage}/event_date={event_date}/"


def sql_string_path(path: Path) -> str:
    """Escape a local path for a single-quoted SQL string, the same way the driver does.

    The path must not be URL-encoded: PUT reads it literally, so encoding the
    "=" in event_date=YYYYMMDD would point it at a folder that does not exist.
    """
    return path.resolve().as_posix().replace("\\", "\\\\").replace("'", "\\'")


def put_sql(local_file: Path, settings: SnowflakeSettings, event_date: str) -> str:
    """Upload one file, uncompressed (Parquet is already compressed), replacing old copies."""
    return (
        f"put 'file://{sql_string_path(local_file)}' '{stage_folder(settings, event_date)}' "
        "auto_compress = false overwrite = true"
    )


def delete_sql(settings: SnowflakeSettings) -> str:
    return f"delete from {settings.events_table} where event_date = %s"  # noqa: S608


def copy_sql(settings: SnowflakeSettings, event_date: str) -> str:
    return (
        f"copy into {settings.events_table}\n"
        f"from '{stage_folder(settings, event_date)}'\n"
        f"file_format = (format_name = '{settings.parquet_format}')\n"
        "match_by_column_name = case_insensitive\n"
        "include_metadata = (\n"
        "    _source_file = metadata$filename,\n"
        "    _loaded_at = metadata$start_scan_time\n"
        ")\n"
        "force = true\n"
        "on_error = abort_statement"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_local_file(raw_dir: Path, entry: dict[str, Any]) -> Path:
    """Return the day's file after checking it matches the extract manifest."""
    path = partition_path(raw_dir, entry["event_date"])
    if not path.is_file():
        msg = f"{entry['event_date']}: extracted file is missing; rerun the extract for that day"
        raise SnowflakeError(msg)
    if _sha256(path) != entry["sha256"]:
        msg = f"{entry['event_date']}: file does not match its manifest checksum; re-extract it"
        raise SnowflakeError(msg)
    return path


def rows_loaded(cursor: Cursor) -> int:
    """Sum rows_loaded across the files reported by a COPY INTO result."""
    results = cursor.fetchall()
    if not results:
        return 0
    index = column_index(cursor, "rows_loaded")
    return sum(int(row[index] or 0) for row in results)


def load_day(
    connection: Connection,
    settings: SnowflakeSettings,
    raw_dir: Path,
    entry: dict[str, Any],
) -> LoadResult:
    """Replace one day in RAW.GA4.EVENTS, all or nothing."""
    event_date = entry["event_date"]
    local_file = verify_local_file(raw_dir, entry)
    cursor = connection.cursor()
    try:
        cursor.execute(put_sql(local_file, settings, event_date))
        cursor.execute("begin")
        try:
            cursor.execute(delete_sql(settings), (event_date,))
            cursor.execute(copy_sql(settings, event_date))
            loaded = rows_loaded(cursor)
            if loaded != entry["rows"]:
                msg = (
                    f"{event_date}: loaded {loaded} rows but the manifest expects "
                    f"{entry['rows']}; the day was rolled back"
                )
                raise SnowflakeError(msg)
            cursor.execute("commit")
        except BaseException:
            cursor.execute("rollback")
            raise
    finally:
        cursor.close()
    logger.info("Loaded %s: %d rows", event_date, loaded)
    return LoadResult(event_date=event_date, rows_expected=entry["rows"], rows_loaded=loaded)


def select_days(
    manifest: dict[str, dict[str, Any]],
    start: date | None,
    end: date | None,
) -> list[dict[str, Any]]:
    """Return manifest entries for the requested days, failing if any day is missing.

    With no dates, every extracted day is selected. With only a start date, the
    range runs to the last extracted day.
    """
    if not manifest:
        msg = "The extract manifest is empty; run the extract first"
        raise ConfigError(msg)
    first = start or _parse_event_date(min(manifest))
    last = end or _parse_event_date(max(manifest))
    try:
        wanted = [day.strftime(EVENT_DATE_FORMAT) for day in date_range(first, last)]
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    missing = [key for key in wanted if key not in manifest]
    if missing:
        msg = (
            f"{len(missing)} requested day(s) are not in the extract manifest, "
            f"first {missing[0]}; extract them first"
        )
        raise ConfigError(msg)
    return [manifest[key] for key in wanted]


def _parse_event_date(value: str) -> date:
    return datetime.strptime(value, EVENT_DATE_FORMAT).replace(tzinfo=UTC).date()


def run(
    connection: Connection,
    settings: SnowflakeSettings,
    raw_dir: Path,
    entries: Sequence[dict[str, Any]],
) -> list[LoadResult]:
    results = [load_day(connection, settings, raw_dir, entry) for entry in entries]
    logger.info(
        "Finished: %d day(s), %d rows loaded",
        len(results),
        sum(result.rows_loaded for result in results),
    )
    return results


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load extracted GA4 days into Snowflake.")
    when = parser.add_mutually_exclusive_group()
    when.add_argument("--date", type=date.fromisoformat, help="One day, YYYY-MM-DD.")
    when.add_argument("--start", type=date.fromisoformat, help="First day, YYYY-MM-DD.")
    parser.add_argument("--end", type=date.fromisoformat, help="Last day, YYYY-MM-DD.")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)
    if args.end is not None and args.date is not None:
        parser.error("--end cannot be combined with --date")
    return args


def main(argv: Sequence[str] | None = None, connection: Connection | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)
    start = args.date or args.start
    end = args.date or args.end
    try:
        raw_dir = ExtractSettings.from_env().raw_data_dir
        entries = select_days(load_manifest(raw_dir), start, end)
        settings = SnowflakeSettings.for_loader()
        connection = connection or connect(settings)
        try:
            run(connection, settings, raw_dir, entries)
        finally:
            connection.close()
    except (ConfigError, SnowflakeError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.error("%s", describe_driver_error(exc))
        return 1
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
