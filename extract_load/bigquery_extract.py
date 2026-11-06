"""Extract GA4 daily events from the BigQuery public dataset to Parquet.

The run works in two phases:

1. Plan: dry-run the query for every requested day. Dry runs are free. The run
   stops before any real query if one day would process more than
   BQ_MAX_BYTES_PER_QUERY, or all days together more than BQ_MAX_BYTES_PER_RUN.
2. Extract: run each day's query with maximum_bytes_billed set to the same
   per-query limit, so BigQuery itself rejects a query that would cost more.

Each day is written to <raw_data_dir>/event_date=YYYYMMDD/part-0.parquet. The
file is written to a temporary name and then renamed, so a rerun replaces the
day completely and an interrupted run never leaves a half-written file.

A row-count manifest (_manifest.json, gitignored with the data folder) records
rows and bytes per day for reconciliation after loading.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import pyarrow as pa
import pyarrow.parquet as pq

from extract_load.config import (
    BIGQUERY_LOCATION,
    GA4_DATASET,
    GA4_TABLE_PREFIX,
    ConfigError,
    ExtractSettings,
)
from extract_load.ga4_schema import EVENT_DATE_FORMAT, GA4_EVENTS_SCHEMA, partition_path
from extract_load.logging_utils import configure_logging

if TYPE_CHECKING:
    from google.cloud import bigquery

logger = logging.getLogger(__name__)

MANIFEST_NAME = "_manifest.json"
BYTES_PER_UNIT = 1024
JOB_LABELS = {"project": "ecommerce-analytics", "step": "extract"}


class BudgetExceededError(RuntimeError):
    """Raised when a planned extraction would process more bytes than allowed."""


class EmptyExtractError(RuntimeError):
    """Raised when a day returns no rows, which means the daily table is missing."""


class QueryClient(Protocol):
    """The part of google.cloud.bigquery.Client this module uses."""

    def query(self, query: str, job_config: Any = ...) -> Any: ...  # noqa: ANN401


@dataclass(frozen=True)
class DayPlan:
    """A day's query and the bytes BigQuery estimates it will process."""

    day: date
    sql: str
    estimated_bytes: int


@dataclass(frozen=True)
class DayResult:
    """What one extracted day produced, as recorded in the manifest."""

    event_date: str
    rows: int
    estimated_bytes: int
    bytes_processed: int
    bytes_billed: int
    file: str
    sha256: str
    extracted_at: str


def date_range(start: date, end: date) -> list[date]:
    """Return every date from start to end, inclusive."""
    if end < start:
        msg = "end date must not be before start date"
        raise ValueError(msg)
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def build_query(day: date) -> str:
    """Return the extraction query for one day.

    The table suffix is formatted from a date object, so it is always eight
    digits. It is written into the SQL as a constant, which lets BigQuery prune
    the wildcard to a single daily table before estimating bytes.
    """
    suffix = day.strftime(EVENT_DATE_FORMAT)
    columns = ",\n    ".join(GA4_EVENTS_SCHEMA.names)
    return (
        f"select\n    {columns}\n"
        f"from `{GA4_DATASET}.{GA4_TABLE_PREFIX}*`\n"
        f"where _TABLE_SUFFIX = '{suffix}'"
    )


def _job_config(*, dry_run: bool, max_bytes: int | None = None) -> bigquery.QueryJobConfig:
    from google.cloud import bigquery  # noqa: PLC0415 - optional dependency group

    config = bigquery.QueryJobConfig(
        dry_run=dry_run,
        use_query_cache=False,
        use_legacy_sql=False,
        labels=JOB_LABELS,
    )
    if max_bytes is not None:
        config.maximum_bytes_billed = max_bytes
    return config


def plan_days(
    client: QueryClient, days: Sequence[date], settings: ExtractSettings
) -> list[DayPlan]:
    """Dry-run every day and enforce the per-query and per-run byte limits."""
    plans: list[DayPlan] = []
    for day in days:
        sql = build_query(day)
        job = client.query(sql, job_config=_job_config(dry_run=True))
        estimated = int(job.total_bytes_processed or 0)
        logger.info("Dry run %s: %s", day.isoformat(), format_bytes(estimated))
        if estimated > settings.max_bytes_per_query:
            msg = (
                f"{day.isoformat()} would process {format_bytes(estimated)}, above the "
                f"per-query limit of {format_bytes(settings.max_bytes_per_query)}"
            )
            raise BudgetExceededError(msg)
        plans.append(DayPlan(day=day, sql=sql, estimated_bytes=estimated))

    total = sum(plan.estimated_bytes for plan in plans)
    logger.info("Planned %d day(s), %s in total", len(plans), format_bytes(total))
    if total > settings.max_bytes_per_run:
        msg = (
            f"The run would process {format_bytes(total)}, above the per-run limit of "
            f"{format_bytes(settings.max_bytes_per_run)}"
        )
        raise BudgetExceededError(msg)
    return plans


def conform_to_schema(table: pa.Table) -> pa.Table:
    """Select the expected columns in order and cast to the project schema."""
    missing = [name for name in GA4_EVENTS_SCHEMA.names if name not in table.column_names]
    if missing:
        msg = f"Query result is missing columns: {', '.join(missing)}"
        raise ValueError(msg)
    return table.select(GA4_EVENTS_SCHEMA.names).cast(GA4_EVENTS_SCHEMA)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_day(table: pa.Table, root: Path, event_date: str) -> Path:
    """Write one day atomically, replacing any earlier file for that day."""
    path = partition_path(root, event_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    pq.write_table(table, temporary, compression="snappy")
    temporary.replace(path)
    return path


def extract_day(client: QueryClient, plan: DayPlan, settings: ExtractSettings) -> DayResult:
    """Run one planned query and write its partition."""
    event_date = plan.day.strftime(EVENT_DATE_FORMAT)
    job = client.query(
        plan.sql,
        job_config=_job_config(dry_run=False, max_bytes=settings.max_bytes_per_query),
    )
    # The Storage Read API is a separately billed service, so results are read
    # through the standard API, which the sandbox includes.
    table = conform_to_schema(job.result().to_arrow(create_bqstorage_client=False))
    if table.num_rows == 0:
        msg = f"{event_date} returned no rows; the daily table may not exist"
        raise EmptyExtractError(msg)

    path = write_day(table, settings.raw_data_dir, event_date)
    result = DayResult(
        event_date=event_date,
        rows=table.num_rows,
        estimated_bytes=plan.estimated_bytes,
        bytes_processed=int(job.total_bytes_processed or 0),
        bytes_billed=int(job.total_bytes_billed or 0),
        file=path.relative_to(settings.raw_data_dir).as_posix(),
        sha256=_sha256(path),
        extracted_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    logger.info(
        "Extracted %s: %d rows, %s processed",
        event_date,
        result.rows,
        format_bytes(result.bytes_processed),
    )
    return result


def load_manifest(root: Path) -> dict[str, dict[str, Any]]:
    path = root / MANIFEST_NAME
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def update_manifest(root: Path, result: DayResult) -> None:
    """Record one day in the manifest, replacing any earlier entry for it."""
    manifest = load_manifest(root)
    manifest[result.event_date] = asdict(result)
    root.mkdir(parents=True, exist_ok=True)
    path = root / MANIFEST_NAME
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n")
    temporary.replace(path)


def summarise_manifest(manifest: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return totals that are safe to share: counts and bytes only."""
    if not manifest:
        return {"days": 0}
    rows = [entry["rows"] for entry in manifest.values()]
    return {
        "days": len(manifest),
        "first_day": min(manifest),
        "last_day": max(manifest),
        "total_rows": sum(rows),
        "min_rows_per_day": min(rows),
        "max_rows_per_day": max(rows),
        "total_bytes_processed": format_bytes(
            sum(entry["bytes_processed"] for entry in manifest.values())
        ),
        "total_bytes_billed": format_bytes(
            sum(entry["bytes_billed"] for entry in manifest.values())
        ),
    }


def format_bytes(value: int) -> str:
    """Format a byte count in binary units, for example 1.50 GiB."""
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < BYTES_PER_UNIT or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= BYTES_PER_UNIT
    return f"{size:.2f} GiB"  # pragma: no cover - loop always returns


def create_client(settings: ExtractSettings) -> bigquery.Client:
    """Create a client from Application Default Credentials."""
    from google.auth.exceptions import DefaultCredentialsError  # noqa: PLC0415
    from google.cloud import bigquery  # noqa: PLC0415 - optional dependency group

    try:
        return bigquery.Client(project=settings.require_project(), location=BIGQUERY_LOCATION)
    except DefaultCredentialsError as exc:
        msg = (
            "Google credentials were not found. Run "
            "'gcloud auth application-default login' and try again."
        )
        raise ConfigError(msg) from exc


def run(
    client: QueryClient,
    settings: ExtractSettings,
    days: Sequence[date],
    *,
    dry_run_only: bool = False,
) -> list[DayResult]:
    """Plan every day, then extract them unless this is a dry run."""
    plans = plan_days(client, days, settings)
    if dry_run_only:
        logger.info("Dry run only: no queries were executed")
        return []
    results: list[DayResult] = []
    for plan in plans:
        result = extract_day(client, plan, settings)
        update_manifest(settings.raw_data_dir, result)
        results.append(result)
    logger.info(
        "Finished: %d day(s), %d rows",
        len(results),
        sum(result.rows for result in results),
    )
    return results


def _resolve_days(args: argparse.Namespace, settings: ExtractSettings) -> list[date]:
    if args.date is not None:
        start = end = args.date
    else:
        start = args.start or settings.first_date
        end = args.end or settings.last_date
    if start < settings.first_date or end > settings.last_date:
        msg = (
            f"Requested dates must fall within {settings.first_date.isoformat()} "
            f"and {settings.last_date.isoformat()}"
        )
        raise ConfigError(msg)
    return date_range(start, end)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract GA4 daily events to Parquet.")
    when = parser.add_mutually_exclusive_group()
    when.add_argument("--date", type=date.fromisoformat, help="One day, YYYY-MM-DD.")
    when.add_argument("--start", type=date.fromisoformat, help="First day, YYYY-MM-DD.")
    parser.add_argument("--end", type=date.fromisoformat, help="Last day, YYYY-MM-DD.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Estimate bytes only; run no queries."
    )
    parser.add_argument("--summary", action="store_true", help="Print manifest totals and exit.")
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)
    if args.end is not None and args.date is not None:
        parser.error("--end cannot be combined with --date")
    return args


def main(argv: Sequence[str] | None = None, client: QueryClient | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)
    try:
        settings = ExtractSettings.from_env()
        if args.summary:
            summary = summarise_manifest(load_manifest(settings.raw_data_dir))
            logger.info("Manifest summary: %s", json.dumps(summary))
            return 0
        days = _resolve_days(args, settings)
        run(
            client or create_client(settings),
            settings,
            days,
            dry_run_only=args.dry_run,
        )
    except (ConfigError, BudgetExceededError, EmptyExtractError) as exc:
        # Expected failures: the message is enough, a traceback adds nothing.
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
