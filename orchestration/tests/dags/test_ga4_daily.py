"""DAG integrity tests for ga4_daily. Run with `astro dev pytest`."""

from __future__ import annotations

import os
from pathlib import Path

# Example DAGs are switched off by setting, not by a DagBag argument, in Airflow 3.3.
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "False")

import pendulum
import pytest
from airflow.dag_processing.dagbag import DagBag
from airflow.timetables.base import DataInterval, TimeRestriction
from airflow.timetables.interval import CronDataIntervalTimetable

DAGS_DIR = Path(__file__).resolve().parents[2] / "dags"
DAG_ID = "ga4_daily"


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAGS_DIR))


@pytest.fixture(scope="module")
def dag(dagbag: DagBag):
    # Read the parsed DAG directly; get_dag() queries the metadata database.
    return dagbag.dags.get(DAG_ID)


def test_no_import_errors(dagbag: DagBag) -> None:
    assert dagbag.import_errors == {}


def test_dag_is_loaded(dag) -> None:
    assert dag is not None


def test_schedule_uses_daily_utc_data_intervals(dag) -> None:
    assert isinstance(dag.timetable, CronDataIntervalTimetable)
    assert dag.catchup is True
    assert dag.max_active_runs == 1


def test_dates_cover_the_dataset(dag) -> None:
    assert dag.start_date == pendulum.datetime(2020, 11, 1, tz="UTC")
    assert dag.end_date == pendulum.datetime(2021, 1, 31, tz="UTC")


def test_backfill_creates_one_run_per_ga4_day(dag) -> None:
    restriction = TimeRestriction(earliest=dag.start_date, latest=dag.end_date, catchup=True)
    intervals: list[DataInterval] = []
    last = None
    while True:
        info = dag.timetable.next_dagrun_info(
            last_automated_data_interval=last, restriction=restriction
        )
        if info is None:
            break
        intervals.append(info.data_interval)
        last = info.data_interval
    assert len(intervals) == 92
    assert intervals[0].start == pendulum.datetime(2020, 11, 1, tz="UTC")
    assert intervals[0].end == pendulum.datetime(2020, 11, 2, tz="UTC")
    assert intervals[-1].start == pendulum.datetime(2021, 1, 31, tz="UTC")


def test_every_task_retries_with_backoff(dag) -> None:
    for task in dag.tasks:
        assert task.retries >= 2, task.task_id
        assert task.retry_exponential_backoff, task.task_id


def test_tags(dag) -> None:
    assert set(dag.tags) >= {"ga4", "elt", "snowflake", "dbt"}


def test_task_order(dag) -> None:
    extract = dag.get_task("extract")
    load = dag.get_task("load")
    reconcile = dag.get_task("reconcile")
    summarize = dag.get_task("summarize")

    assert extract.downstream_task_ids == {"load", "summarize"}
    assert "reconcile" in load.downstream_task_ids
    dbt_tasks = [task for task in dag.tasks if task.task_id.startswith("dbt_build.")]
    assert dbt_tasks, "the Cosmos task group rendered no dbt tasks"
    dbt_roots = {task.task_id for task in dbt_tasks if not task.upstream_task_ids - {"reconcile"}}
    assert dbt_roots <= reconcile.downstream_task_ids
    assert {task.task_id for task in dbt_tasks if not task.downstream_task_ids - {"summarize"}} <= (
        summarize.upstream_task_ids
    )


def test_day_comes_from_the_data_interval(dag) -> None:
    for task_id in ("extract", "load", "reconcile"):
        assert list(dag.get_task(task_id).op_args) == ["{{ data_interval_start | ds }}"]
