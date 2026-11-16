"""Daily GA4 pipeline: extract, load, reconcile, then build and test dbt.

One run processes one GA4 day, taken from the run's data interval: the run for
2020-11-05 extracts the 2020-11-05 daily table. The schedule covers the 92
days of the public sample, with catchup on, so turning the DAG on backfills
every day in order (one run at a time).

Every step is idempotent: extract overwrites the day's Parquet file, load
replaces the day's rows in one transaction, reconcile only reads, and dbt
merges on event keys and rebuilds the marts. A failed day can be cleared and
rerun, and the whole range can be backfilled again, without duplicates.

Extract, load and reconcile run in their own virtual environment (el_venv)
with the project's pinned library versions, and dbt runs from dbt_venv
through Cosmos, so neither changes the packages Airflow depends on.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import pendulum
from airflow.sdk import chain, dag, task
from airflow.timetables.interval import CronDataIntervalTimetable
from cosmos import DbtTaskGroup, ExecutionConfig, ProfileConfig, ProjectConfig, RenderConfig
from cosmos.constants import InvocationMode, TestBehavior
from cosmos.profiles import SnowflakeEncryptedPrivateKeyFilePemProfileMapping

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(os.environ.get("PROJECT_ROOT", "/usr/local/airflow/project"))
EL_PYTHON = os.environ.get("EL_PYTHON", "/usr/local/airflow/el_venv/bin/python")
DBT_EXECUTABLE = os.environ.get("DBT_EXECUTABLE", "/usr/local/airflow/dbt_venv/bin/dbt")
SNOWFLAKE_DBT_CONN_ID = "snowflake_dbt"
DAY = "{{ data_interval_start | ds }}"

DEFAULT_ARGS = {
    "owner": "analytics-engineering",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=20),
    "execution_timeout": timedelta(hours=1),
}


@dag(
    dag_id="ga4_daily",
    description="Extract, load, reconcile and transform one day of GA4 e-commerce events.",
    # Explicit data intervals: the run for a day starts when that day has ended
    # and covers exactly that day in UTC, the GA4 sample's day boundary.
    schedule=CronDataIntervalTimetable("0 0 * * *", timezone="UTC"),
    start_date=pendulum.datetime(2020, 11, 1, tz="UTC"),
    end_date=pendulum.datetime(2021, 1, 31, tz="UTC"),
    catchup=True,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["ga4", "elt", "snowflake", "dbt"],
    doc_md=__doc__,
)
def ga4_daily() -> None:
    @task.external_python(python=EL_PYTHON, expect_airflow=False)
    def extract(day: str) -> dict[str, Any]:
        """Extract the day from BigQuery to Parquet, within the byte limits."""
        from extract_load.airflow_tasks import run_extract  # noqa: PLC0415

        return run_extract(day)

    @task.external_python(python=EL_PYTHON, expect_airflow=False)
    def load(day: str) -> dict[str, Any]:
        """Replace the day in RAW.GA4.EVENTS in one transaction."""
        from extract_load.airflow_tasks import run_load  # noqa: PLC0415

        return run_load(day)

    @task.external_python(python=EL_PYTHON, expect_airflow=False)
    def reconcile(day: str) -> dict[str, Any]:
        """Check row counts per day between the extract manifest and Snowflake."""
        from extract_load.airflow_tasks import run_reconcile  # noqa: PLC0415

        return run_reconcile(day)

    dbt_build = DbtTaskGroup(
        group_id="dbt_build",
        project_config=ProjectConfig(
            dbt_project_path=PROJECT_ROOT / "transform",
            # Packages are installed on the Mac with `make dbt-deps` and copied
            # with the project, so tasks do not download them on every run.
            install_dbt_deps=False,
            copy_dbt_packages=True,
        ),
        profile_config=ProfileConfig(
            profile_name="ecommerce_analytics",
            target_name="prod",
            profile_mapping=SnowflakeEncryptedPrivateKeyFilePemProfileMapping(
                conn_id=SNOWFLAKE_DBT_CONN_ID,
            ),
        ),
        # dbt lives in its own virtual environment, so Cosmos calls that
        # executable as a subprocess instead of importing dbt into Airflow.
        execution_config=ExecutionConfig(
            dbt_executable_path=DBT_EXECUTABLE,
            invocation_mode=InvocationMode.SUBPROCESS,
        ),
        render_config=RenderConfig(
            dbt_executable_path=DBT_EXECUTABLE,
            invocation_mode=InvocationMode.SUBPROCESS,
            # One task per model that runs the model and its tests together.
            test_behavior=TestBehavior.BUILD,
            dbt_deps=False,
        ),
    )

    @task
    def summarize(
        extracted: dict[str, Any], loaded: dict[str, Any], reconciled: dict[str, Any]
    ) -> dict[str, Any]:
        """Log one line per run with the day's counts, after dbt has finished."""
        summary = {
            "event_date": reconciled["event_date"],
            "rows_extracted": extracted["rows"],
            "bytes_processed": extracted["bytes_processed"],
            "rows_loaded": loaded["rows_loaded"],
            "days_matched": reconciled["days_matched"],
            "total_rows_in_snowflake": reconciled["total_rows"],
        }
        logger.info("Run summary: %s", summary)
        return summary

    extracted = extract(DAY)
    loaded = load(DAY)
    reconciled = reconcile(DAY)
    summary = summarize(extracted, loaded, reconciled)
    chain(extracted, loaded, reconciled, dbt_build, summary)


ga4_daily()
