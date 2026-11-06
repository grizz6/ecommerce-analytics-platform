from datetime import date
from pathlib import Path

import pytest
from snowflake.connector.errors import ProgrammingError

from extract_load import snowflake_load as sl
from extract_load.config import ConfigError
from extract_load.snowflake_client import SnowflakeError, SnowflakeSettings
from tests.conftest import ACCOUNT, PASSPHRASE, ExtractedData
from tests.fake_snowflake import FakeSnowflake


def _fake(extracted: ExtractedData) -> FakeSnowflake:
    return FakeSnowflake(
        rows_per_file={day: int(entry["rows"]) for day, entry in extracted.manifest.items()}
    )


def _settings() -> SnowflakeSettings:
    return SnowflakeSettings.for_loader()


def test_put_replaces_the_day_folder_without_recompressing(loader_env: ExtractedData) -> None:
    local = loader_env.raw_dir / "event_date=20201101" / "part-0.parquet"
    sql = sl.put_sql(local, _settings(), "20201101")
    assert sql.startswith("put 'file://")
    assert "'@RAW.GA4.EVENTS_STAGE/event_date=20201101/'" in sql
    assert "auto_compress = false" in sql
    assert "overwrite = true" in sql


def test_copy_matches_columns_and_adds_metadata(loader_env: ExtractedData) -> None:
    sql = sl.copy_sql(_settings(), "20201101")
    assert sql.startswith(
        "copy into RAW.GA4.EVENTS\nfrom '@RAW.GA4.EVENTS_STAGE/event_date=20201101/'"
    )
    assert "format_name = 'RAW.GA4.PARQUET_FORMAT'" in sql
    assert "match_by_column_name = case_insensitive" in sql
    assert "_source_file = metadata$filename" in sql
    assert "_loaded_at = metadata$start_scan_time" in sql
    assert "force = true" in sql
    assert "on_error = abort_statement" in sql


def test_load_day_runs_in_one_transaction(loader_env: ExtractedData) -> None:
    db = _fake(loader_env)
    entry = loader_env.manifest["20201101"]
    result = sl.load_day(db, _settings(), loader_env.raw_dir, entry)

    assert db.statements == ["put", "begin", "delete", "copy", "commit"]
    assert db.executed[2][1] == ("20201101",)
    assert result.rows_loaded == result.rows_expected == entry["rows"]
    assert db.table == {"20201101": entry["rows"]}


def test_rerun_replaces_the_day_without_duplicates(loader_env: ExtractedData) -> None:
    db = _fake(loader_env)
    entries = list(loader_env.manifest.values())
    sl.run(db, _settings(), loader_env.raw_dir, entries)
    sl.run(db, _settings(), loader_env.raw_dir, entries[:1])
    assert db.table == {day: entry["rows"] for day, entry in loader_env.manifest.items()}


def test_count_mismatch_rolls_back_and_keeps_previous_data(loader_env: ExtractedData) -> None:
    db = _fake(loader_env)
    entry = loader_env.manifest["20201101"]
    sl.load_day(db, _settings(), loader_env.raw_dir, entry)

    db.rows_per_file["20201101"] = int(entry["rows"]) - 1
    with pytest.raises(SnowflakeError, match="rolled back"):
        sl.load_day(db, _settings(), loader_env.raw_dir, entry)
    assert db.statements[-1] == "rollback"
    assert db.table == {"20201101": entry["rows"]}


def test_failed_copy_rolls_back(loader_env: ExtractedData) -> None:
    db = _fake(loader_env)
    db.fail_on = "copy"
    with pytest.raises(RuntimeError, match="simulated"):
        sl.load_day(db, _settings(), loader_env.raw_dir, loader_env.manifest["20201101"])
    assert db.statements[-1] == "rollback"
    assert db.table == {}


def test_checksum_mismatch_stops_before_any_statement(loader_env: ExtractedData) -> None:
    path = loader_env.raw_dir / "event_date=20201102" / "part-0.parquet"
    path.write_bytes(path.read_bytes() + b"tampered")
    db = _fake(loader_env)
    with pytest.raises(SnowflakeError, match="checksum"):
        sl.load_day(db, _settings(), loader_env.raw_dir, loader_env.manifest["20201102"])
    assert db.executed == []


def test_missing_file_stops_before_any_statement(loader_env: ExtractedData) -> None:
    (loader_env.raw_dir / "event_date=20201103" / "part-0.parquet").unlink()
    db = _fake(loader_env)
    with pytest.raises(SnowflakeError, match="missing"):
        sl.load_day(db, _settings(), loader_env.raw_dir, loader_env.manifest["20201103"])
    assert db.executed == []


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (None, None, ["20201101", "20201102", "20201103"]),
        (date(2020, 11, 2), None, ["20201102", "20201103"]),
        (date(2020, 11, 2), date(2020, 11, 2), ["20201102"]),
    ],
)
def test_select_days(
    extracted: ExtractedData, start: date | None, end: date | None, expected: list[str]
) -> None:
    selected = sl.select_days(extracted.manifest, start, end)
    assert [entry["event_date"] for entry in selected] == expected


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (date(2020, 10, 31), date(2020, 11, 1), "not in the extract manifest"),
        (date(2020, 11, 3), date(2020, 11, 4), "not in the extract manifest"),
        (date(2020, 11, 3), date(2020, 11, 1), "before"),
    ],
)
def test_select_days_rejects_bad_ranges(
    extracted: ExtractedData, start: date, end: date, message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        sl.select_days(extracted.manifest, start, end)


def test_select_days_requires_a_manifest() -> None:
    with pytest.raises(ConfigError, match="empty"):
        sl.select_days({}, None, None)


def test_main_loads_all_days_and_logs_counts_only(
    loader_env: ExtractedData, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _fake(loader_env)
    assert sl.main([], connection=db) == 0
    assert db.closed
    assert db.table == {day: entry["rows"] for day, entry in loader_env.manifest.items()}

    logged = capsys.readouterr().err
    assert "Finished: 3 day(s)" in logged
    for secret_or_identifier in (ACCOUNT, PASSPHRASE, str(Path.home())):
        assert secret_or_identifier not in logged


def test_main_single_day(loader_env: ExtractedData) -> None:
    db = _fake(loader_env)
    assert sl.main(["--date", "2020-11-02"], connection=db) == 0
    assert list(db.table) == ["20201102"]


def test_main_reports_sql_errors_and_fails(
    loader_env: ExtractedData, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _fake(loader_env)

    def reject(*_args: object, **_kwargs: object) -> None:
        raise ProgrammingError(
            msg="Insufficient privileges to operate on table 'EVENTS'", errno=3001
        )

    monkeypatch.setattr(sl, "run", reject)
    assert sl.main([], connection=db) == 1
    assert "Insufficient privileges" in capsys.readouterr().err
    assert db.closed


def test_main_fails_cleanly_without_settings(
    loader_env: ExtractedData, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SNOWFLAKE_ACCOUNT")
    assert sl.main([], connection=_fake(loader_env)) == 1


def test_date_and_end_cannot_be_combined() -> None:
    with pytest.raises(SystemExit):
        sl.parse_args(["--date", "2020-11-01", "--end", "2020-11-02"])
