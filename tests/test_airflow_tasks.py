"""Tests for the functions the Airflow DAG calls, with fake BigQuery and Snowflake."""

from typing import Any

import pytest

from extract_load import airflow_tasks
from tests.conftest import ExtractedData
from tests.fake_snowflake import FakeSnowflake


def _fake_snowflake(extracted: ExtractedData, loaded_days: list[str]) -> FakeSnowflake:
    rows = {day: int(entry["rows"]) for day, entry in extracted.manifest.items()}
    return FakeSnowflake(
        rows_per_file=rows,
        table={day: rows[day] for day in loaded_days},
    )


@pytest.fixture
def snowflake(loader_env: ExtractedData, monkeypatch: pytest.MonkeyPatch) -> FakeSnowflake:
    db = _fake_snowflake(loader_env, loaded_days=[])
    monkeypatch.setattr(airflow_tasks, "connect", lambda _settings: db)
    return db


def test_load_then_reconcile_one_day(loader_env: ExtractedData, snowflake: FakeSnowflake) -> None:
    for day in ("2020-11-01", "2020-11-02", "2020-11-03"):
        loaded = airflow_tasks.run_load(day)
        assert loaded["rows_loaded"] == loader_env.manifest[loaded["event_date"]]["rows"]

    summary = airflow_tasks.run_reconcile("2020-11-02")
    assert summary == {
        "event_date": "20201102",
        "rows": loader_env.manifest["20201102"]["rows"],
        "days_matched": 3,
        "total_rows": sum(int(e["rows"]) for e in loader_env.manifest.values()),
    }
    assert snowflake.closed


def test_load_is_idempotent(loader_env: ExtractedData, snowflake: FakeSnowflake) -> None:
    airflow_tasks.run_load("2020-11-01")
    airflow_tasks.run_load("2020-11-01")
    assert snowflake.table == {"20201101": loader_env.manifest["20201101"]["rows"]}


def test_reconcile_fails_when_day_is_missing(
    loader_env: ExtractedData, snowflake: FakeSnowflake
) -> None:
    airflow_tasks.run_load("2020-11-01")
    with pytest.raises(airflow_tasks.PipelineStepError, match="20201102 does not match"):
        airflow_tasks.run_reconcile("2020-11-02")


def test_reconcile_fails_when_another_day_differs(
    loader_env: ExtractedData, snowflake: FakeSnowflake
) -> None:
    for day in ("2020-11-01", "2020-11-02", "2020-11-03"):
        airflow_tasks.run_load(day)
    snowflake.table["20201103"] -= 1
    with pytest.raises(airflow_tasks.PipelineStepError, match="differ"):
        airflow_tasks.run_reconcile("2020-11-01")


def test_load_rejects_a_day_that_was_not_extracted(
    loader_env: ExtractedData, snowflake: FakeSnowflake
) -> None:
    with pytest.raises(Exception, match="not in the extract manifest"):
        airflow_tasks.run_load("2020-11-05")
    assert snowflake.executed == []


def test_bad_day_format_is_rejected() -> None:
    with pytest.raises(airflow_tasks.PipelineStepError, match="YYYY-MM-DD"):
        airflow_tasks.run_load("20201101")


def test_extract_runs_one_day_and_returns_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    calls: dict[str, Any] = {}

    class Result:
        event_date = "20201101"
        rows = 31272
        bytes_processed = 22_000_000

    def fake_run(client: object, settings: object, days: list[Any]) -> list[Result]:
        calls["client"] = client
        calls["days"] = days
        return [Result()]

    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(airflow_tasks.bigquery_extract, "create_client", lambda _s: "client")
    monkeypatch.setattr(airflow_tasks.bigquery_extract, "run", fake_run)

    summary = airflow_tasks.run_extract("2020-11-01")
    assert summary == {"event_date": "20201101", "rows": 31272, "bytes_processed": 22_000_000}
    assert calls["client"] == "client"
    assert [day.isoformat() for day in calls["days"]] == ["2020-11-01"]
