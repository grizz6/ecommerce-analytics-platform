"""Compare per-day row counts between the extract manifest and Snowflake.

Exits with status 1 if any day is missing from Snowflake, present in Snowflake
but not extracted, or has a different row count. Output is counts only.
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from extract_load.bigquery_extract import load_manifest
from extract_load.config import ConfigError, ExtractSettings
from extract_load.logging_utils import configure_logging
from extract_load.snowflake_client import (
    Connection,
    SnowflakeError,
    SnowflakeSettings,
    connect,
    describe_driver_error,
)

logger = logging.getLogger(__name__)

MAX_DAYS_LISTED = 10


@dataclass(frozen=True)
class Reconciliation:
    """The result of comparing expected and loaded counts per day."""

    matched: list[str] = field(default_factory=list)
    missing_in_snowflake: list[str] = field(default_factory=list)
    unexpected_in_snowflake: list[str] = field(default_factory=list)
    count_mismatches: dict[str, tuple[int, int]] = field(default_factory=dict)
    expected_rows: int = 0
    loaded_rows: int = 0

    @property
    def ok(self) -> bool:
        return not (
            self.missing_in_snowflake or self.unexpected_in_snowflake or self.count_mismatches
        )


def counts_sql(settings: SnowflakeSettings) -> str:
    return (
        f"select event_date, count(*) as row_count from {settings.events_table} "  # noqa: S608
        "group by event_date order by event_date"
    )


def fetch_counts(connection: Connection, settings: SnowflakeSettings) -> dict[str, int]:
    cursor = connection.cursor()
    try:
        cursor.execute(counts_sql(settings))
        return {str(event_date): int(count) for event_date, count in cursor.fetchall()}
    finally:
        cursor.close()


def compare(expected: Mapping[str, int], loaded: Mapping[str, int]) -> Reconciliation:
    matched, mismatches = [], {}
    for day in sorted(set(expected) & set(loaded)):
        if expected[day] == loaded[day]:
            matched.append(day)
        else:
            mismatches[day] = (expected[day], loaded[day])
    return Reconciliation(
        matched=matched,
        missing_in_snowflake=sorted(set(expected) - set(loaded)),
        unexpected_in_snowflake=sorted(set(loaded) - set(expected)),
        count_mismatches=mismatches,
        expected_rows=sum(expected.values()),
        loaded_rows=sum(loaded.values()),
    )


def _listed(days: Sequence[str]) -> str:
    shown = ", ".join(days[:MAX_DAYS_LISTED])
    extra = len(days) - MAX_DAYS_LISTED
    return f"{shown} and {extra} more" if extra > 0 else shown


def report(result: Reconciliation) -> None:
    logger.info(
        "Days matched: %d. Rows expected: %d. Rows in Snowflake: %d.",
        len(result.matched),
        result.expected_rows,
        result.loaded_rows,
    )
    if result.missing_in_snowflake:
        logger.error(
            "%d day(s) extracted but not loaded: %s",
            len(result.missing_in_snowflake),
            _listed(result.missing_in_snowflake),
        )
    if result.unexpected_in_snowflake:
        logger.error(
            "%d day(s) in Snowflake but not in the manifest: %s",
            len(result.unexpected_in_snowflake),
            _listed(result.unexpected_in_snowflake),
        )
    for day, (expected, loaded) in list(result.count_mismatches.items())[:MAX_DAYS_LISTED]:
        logger.error("%s: expected %d rows, found %d", day, expected, loaded)
    if result.ok:
        logger.info("Reconciliation passed")
    else:
        logger.error("Reconciliation failed")


def main(argv: Sequence[str] | None = None, connection: Connection | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile extracted and loaded row counts.")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    try:
        manifest = load_manifest(ExtractSettings.from_env().raw_data_dir)
        if not manifest:
            msg = "The extract manifest is empty; nothing to reconcile"
            raise ConfigError(msg)
        settings = SnowflakeSettings.for_loader()
        connection = connection or connect(settings)
        try:
            loaded = fetch_counts(connection, settings)
        finally:
            connection.close()
    except (ConfigError, SnowflakeError) as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.error("%s", describe_driver_error(exc))
        return 1
    result = compare({day: entry["rows"] for day, entry in manifest.items()}, loaded)
    report(result)
    return 0 if result.ok else 1


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
