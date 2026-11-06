"""Unit tests for the BigQuery extractor, using a fake client.

No test touches the network or needs credentials. The fake client returns
synthetic fixture rows shaped like a BigQuery result: columns in a different
order, an extra column the extractor does not keep, and list element names
that differ from the project schema.
"""

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery

from extract_load import bigquery_extract as bx
from extract_load.config import ConfigError, ExtractSettings
from extract_load.ga4_schema import GA4_EVENTS_SCHEMA
from scripts.generate_fixtures import FixtureConfig, generate_events

DAY_ONE = date(2020, 11, 1)
DAY_TWO = date(2020, 11, 2)


@pytest.fixture(scope="module")
def fixture_rows() -> list[dict[str, Any]]:
    config = FixtureConfig(seed=11, users=120, start=DAY_ONE, end=date(2020, 11, 3))
    return generate_events(config)


def _bigquery_shaped(rows: list[dict[str, Any]]) -> pa.Table:
    """Build a table the way BigQuery returns it, not the way the project stores it."""
    table = pa.Table.from_pylist(rows, schema=GA4_EVENTS_SCHEMA)
    renamed_fields = []
    for schema_field in table.schema:
        field_type = schema_field.type
        if pa.types.is_list(field_type):
            field_type = pa.list_(pa.field("element", field_type.value_type))
        renamed_fields.append(pa.field(schema_field.name, field_type))
    table = table.cast(pa.schema(renamed_fields))
    table = table.append_column("stream_id", pa.array([1] * table.num_rows, pa.int64()))
    return table.select(list(reversed(table.column_names)))


@dataclass
class FakeResult:
    table: pa.Table
    bqstorage_requested: bool | None = None

    def to_arrow(self, *, create_bqstorage_client: bool = True) -> pa.Table:
        self.bqstorage_requested = create_bqstorage_client
        return self.table


@dataclass
class FakeJob:
    total_bytes_processed: int | None
    total_bytes_billed: int | None
    result_table: pa.Table | None = None

    def result(self) -> FakeResult:
        assert self.result_table is not None, "dry-run jobs have no result"
        return FakeResult(self.result_table)


@dataclass
class FakeClient:
    rows: list[dict[str, Any]]
    bytes_per_day: dict[str, int] = field(default_factory=dict)
    default_bytes: int = 50 * 1024**2
    calls: list[tuple[str, Any]] = field(default_factory=list)

    def query(self, query: str, job_config: Any = None) -> FakeJob:
        self.calls.append((query, job_config))
        suffix = query.rsplit("'", 2)[-2]
        estimated = self.bytes_per_day.get(suffix, self.default_bytes)
        if job_config.dry_run:
            return FakeJob(total_bytes_processed=estimated, total_bytes_billed=0)
        day_rows = [row for row in self.rows if row["event_date"] == suffix]
        return FakeJob(
            total_bytes_processed=estimated,
            total_bytes_billed=estimated,
            result_table=_bigquery_shaped(day_rows) if day_rows else _empty_result(),
        )

    @property
    def executed(self) -> list[tuple[str, Any]]:
        return [call for call in self.calls if not call[1].dry_run]


def _empty_result() -> pa.Table:
    return GA4_EVENTS_SCHEMA.empty_table()


def _settings(tmp_path: Path, **overrides: str) -> ExtractSettings:
    env = {"GCP_PROJECT_ID": "test-project", "RAW_DATA_DIR": str(tmp_path / "raw")}
    env.update(overrides)
    return ExtractSettings.from_env(env)


def test_date_range_is_inclusive() -> None:
    assert bx.date_range(DAY_ONE, DAY_TWO) == [DAY_ONE, DAY_TWO]
    assert bx.date_range(DAY_ONE, DAY_ONE) == [DAY_ONE]
    with pytest.raises(ValueError, match="before"):
        bx.date_range(DAY_TWO, DAY_ONE)


def test_query_selects_only_schema_columns_for_one_table() -> None:
    sql = bx.build_query(DAY_ONE)
    assert "select *" not in sql.lower()
    assert "`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`" in sql
    assert sql.endswith("where _TABLE_SUFFIX = '20201101'")
    for column in GA4_EVENTS_SCHEMA.names:
        assert f"    {column}" in sql
    assert "privacy_info" not in sql


def test_dry_run_only_executes_nothing(tmp_path: Path, fixture_rows: list[dict[str, Any]]) -> None:
    client = FakeClient(fixture_rows)
    results = bx.run(client, _settings(tmp_path), [DAY_ONE, DAY_TWO], dry_run_only=True)
    assert results == []
    assert len(client.calls) == 2
    assert client.executed == []
    assert not (tmp_path / "raw").exists()


def test_dry_run_config_disables_cache_and_labels_jobs(
    tmp_path: Path, fixture_rows: list[dict[str, Any]]
) -> None:
    client = FakeClient(fixture_rows)
    bx.run(client, _settings(tmp_path), [DAY_ONE], dry_run_only=True)
    config = client.calls[0][1]
    assert config.dry_run is True
    assert config.use_query_cache is False
    assert config.use_legacy_sql is False
    assert config.labels == bx.JOB_LABELS


def test_day_over_query_limit_stops_before_any_query_runs(
    tmp_path: Path, fixture_rows: list[dict[str, Any]]
) -> None:
    client = FakeClient(fixture_rows, bytes_per_day={"20201102": 3 * 1024**3})
    with pytest.raises(bx.BudgetExceededError, match=r"2020-11-02 would process 3\.00 GiB"):
        bx.run(client, _settings(tmp_path), [DAY_ONE, DAY_TWO])
    assert client.executed == []


def test_run_over_total_limit_stops_before_any_query_runs(
    tmp_path: Path, fixture_rows: list[dict[str, Any]]
) -> None:
    client = FakeClient(fixture_rows, default_bytes=600)
    settings = _settings(tmp_path, BQ_MAX_BYTES_PER_QUERY="1000", BQ_MAX_BYTES_PER_RUN="1000")
    with pytest.raises(bx.BudgetExceededError, match="per-run limit"):
        bx.run(client, settings, [DAY_ONE, DAY_TWO])
    assert client.executed == []


def test_extract_writes_partitions_matching_schema(
    tmp_path: Path, fixture_rows: list[dict[str, Any]]
) -> None:
    client = FakeClient(fixture_rows)
    settings = _settings(tmp_path)
    results = bx.run(client, settings, [DAY_ONE, DAY_TWO])

    assert [r.event_date for r in results] == ["20201101", "20201102"]
    for result in results:
        path = settings.raw_data_dir / f"event_date={result.event_date}" / "part-0.parquet"
        table = pq.read_table(path)
        assert table.schema.equals(GA4_EVENTS_SCHEMA)
        assert table.num_rows == result.rows
        expected = sum(1 for row in fixture_rows if row["event_date"] == result.event_date)
        assert result.rows == expected
        assert set(table.column("event_date").to_pylist()) == {result.event_date}


def test_real_queries_carry_the_server_side_byte_cap(
    tmp_path: Path, fixture_rows: list[dict[str, Any]]
) -> None:
    client = FakeClient(fixture_rows)
    settings = _settings(tmp_path, BQ_MAX_BYTES_PER_QUERY="123456789")
    bx.run(client, settings, [DAY_ONE])
    (_, config) = client.executed[0]
    assert config.dry_run is False
    assert config.maximum_bytes_billed == 123456789


def test_rerun_overwrites_day_without_leftovers(
    tmp_path: Path, fixture_rows: list[dict[str, Any]]
) -> None:
    settings = _settings(tmp_path)
    first = bx.run(FakeClient(fixture_rows), settings, [DAY_ONE])
    second = bx.run(FakeClient(fixture_rows), settings, [DAY_ONE])

    day_dir = settings.raw_data_dir / "event_date=20201101"
    assert sorted(p.name for p in day_dir.iterdir()) == ["part-0.parquet"]
    assert first[0].sha256 == second[0].sha256
    assert first[0].rows == second[0].rows


def test_manifest_records_each_day_once(tmp_path: Path, fixture_rows: list[dict[str, Any]]) -> None:
    settings = _settings(tmp_path)
    bx.run(FakeClient(fixture_rows), settings, [DAY_ONE, DAY_TWO])
    bx.run(FakeClient(fixture_rows), settings, [DAY_TWO])

    manifest = json.loads((settings.raw_data_dir / "_manifest.json").read_text())
    assert list(manifest) == ["20201101", "20201102"]
    entry = manifest["20201101"]
    assert entry["file"] == "event_date=20201101/part-0.parquet"
    assert entry["bytes_billed"] == entry["bytes_processed"] == entry["estimated_bytes"]
    assert set(entry) == {
        "event_date",
        "rows",
        "estimated_bytes",
        "bytes_processed",
        "bytes_billed",
        "file",
        "sha256",
        "extracted_at",
    }


def test_empty_day_fails_and_writes_nothing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with pytest.raises(bx.EmptyExtractError, match="no rows"):
        bx.run(FakeClient(rows=[]), settings, [DAY_ONE])
    assert not (settings.raw_data_dir / "event_date=20201101").exists()


def test_results_are_read_without_the_storage_api(
    tmp_path: Path, fixture_rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool | None] = []
    original = FakeResult.to_arrow

    def spy(self: FakeResult, *, create_bqstorage_client: bool = True) -> pa.Table:
        seen.append(create_bqstorage_client)
        return original(self, create_bqstorage_client=create_bqstorage_client)

    monkeypatch.setattr(FakeResult, "to_arrow", spy)
    bx.run(FakeClient(fixture_rows), _settings(tmp_path), [DAY_ONE])
    assert seen == [False]


def test_conform_rejects_missing_columns() -> None:
    table = pa.table({"event_date": ["20201101"]})
    with pytest.raises(ValueError, match="missing columns"):
        bx.conform_to_schema(table)


def test_summary_contains_counts_and_bytes_only() -> None:
    manifest = {
        "20201101": {"rows": 10, "bytes_processed": 1024, "bytes_billed": 2048},
        "20201102": {"rows": 30, "bytes_processed": 1024, "bytes_billed": 0},
    }
    assert bx.summarise_manifest(manifest) == {
        "days": 2,
        "first_day": "20201101",
        "last_day": "20201102",
        "total_rows": 40,
        "min_rows_per_day": 10,
        "max_rows_per_day": 30,
        "total_bytes_processed": "2.00 KiB",
        "total_bytes_billed": "2.00 KiB",
    }
    assert bx.summarise_manifest({}) == {"days": 0}


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0 B"), (1023, "1023 B"), (1536, "1.50 KiB"), (5 * 1024**3, "5.00 GiB")],
)
def test_format_bytes(value: int, expected: str) -> None:
    assert bx.format_bytes(value) == expected


def test_main_single_day_and_summary(
    tmp_path: Path,
    fixture_rows: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # main() configures logging itself, so its output is read from stderr.
    monkeypatch.setenv("GCP_PROJECT_ID", "test-project")
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path / "raw"))
    assert bx.main(["--date", "2020-11-01"], client=FakeClient(fixture_rows)) == 0
    assert bx.main(["--summary"]) == 0

    logged = capsys.readouterr().err
    assert '"days": 1' in logged
    assert "test-project" not in logged
    assert str(tmp_path) not in logged


def test_main_range_dry_run(
    tmp_path: Path, fixture_rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path / "raw"))
    client = FakeClient(fixture_rows)
    args = ["--start", "2020-11-01", "--end", "2020-11-03", "--dry-run"]
    assert bx.main(args, client=client) == 0
    assert len(client.calls) == 3
    assert client.executed == []


def test_main_defaults_to_full_configured_range(
    tmp_path: Path, fixture_rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path / "raw"))
    monkeypatch.setenv("GA4_START_DATE", "2020-11-01")
    monkeypatch.setenv("GA4_END_DATE", "2020-11-05")
    client = FakeClient(fixture_rows)
    assert bx.main(["--dry-run"], client=client) == 0
    assert len(client.calls) == 5


@pytest.mark.parametrize(
    "args",
    [["--date", "2020-10-31"], ["--start", "2021-01-30", "--end", "2021-02-02"]],
)
def test_main_rejects_dates_outside_dataset(
    args: list[str], fixture_rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GA4_START_DATE", raising=False)
    monkeypatch.delenv("GA4_END_DATE", raising=False)
    client = FakeClient(fixture_rows)
    assert bx.main(args, client=client) == 1
    assert client.calls == []


def test_main_returns_error_when_over_budget(
    tmp_path: Path, fixture_rows: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path / "raw"))
    client = FakeClient(fixture_rows, default_bytes=5 * 1024**3)
    assert bx.main(["--date", "2020-11-01"], client=client) == 1
    assert client.executed == []


def test_date_and_end_cannot_be_combined() -> None:
    with pytest.raises(SystemExit):
        bx.parse_args(["--date", "2020-11-01", "--end", "2020-11-02"])


def test_create_client_requires_project(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="GCP_PROJECT_ID"):
        bx.create_client(ExtractSettings.from_env({}))


def test_create_client_explains_missing_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_credentials(*_args: object, **_kwargs: object) -> None:
        raise DefaultCredentialsError("none")

    monkeypatch.setattr(bigquery, "Client", no_credentials)
    settings = ExtractSettings.from_env({"GCP_PROJECT_ID": "test-project"})
    with pytest.raises(ConfigError, match="application-default login"):
        bx.create_client(settings)
