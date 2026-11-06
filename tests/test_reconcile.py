import pytest
from snowflake.connector.errors import ProgrammingError

from extract_load import reconcile as rc
from tests.conftest import ACCOUNT, ExtractedData
from tests.fake_snowflake import FakeSnowflake


def _loaded(extracted: ExtractedData, **changes: int | None) -> FakeSnowflake:
    table = {day: int(entry["rows"]) for day, entry in extracted.manifest.items()}
    for day, count in changes.items():
        key = day.removeprefix("d")
        if count is None:
            table.pop(key)
        else:
            table[key] = count
    return FakeSnowflake(table=table)


def test_compare_identifies_every_kind_of_difference() -> None:
    result = rc.compare(
        expected={"20201101": 10, "20201102": 20, "20201103": 30},
        loaded={"20201101": 10, "20201102": 19, "20201104": 5},
    )
    assert result.matched == ["20201101"]
    assert result.count_mismatches == {"20201102": (20, 19)}
    assert result.missing_in_snowflake == ["20201103"]
    assert result.unexpected_in_snowflake == ["20201104"]
    assert (result.expected_rows, result.loaded_rows) == (60, 34)
    assert not result.ok


def test_compare_passes_when_identical() -> None:
    assert rc.compare({"20201101": 10}, {"20201101": 10}).ok


def test_main_passes_when_counts_match(
    loader_env: ExtractedData, capsys: pytest.CaptureFixture[str]
) -> None:
    db = _loaded(loader_env)
    assert rc.main([], connection=db) == 0
    logged = capsys.readouterr().err
    assert "Days matched: 3" in logged
    assert "Reconciliation passed" in logged
    assert ACCOUNT not in logged
    assert db.closed


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"d20201102": 1}, "20201102: expected"),
        ({"d20201103": None}, "extracted but not loaded"),
        ({"d20201231": 7}, "in Snowflake but not in the manifest"),
    ],
)
def test_main_fails_on_any_difference(
    loader_env: ExtractedData,
    capsys: pytest.CaptureFixture[str],
    changes: dict[str, int | None],
    message: str,
) -> None:
    assert rc.main([], connection=_loaded(loader_env, **changes)) == 1
    logged = capsys.readouterr().err
    assert message in logged
    assert "Reconciliation failed" in logged


def test_long_lists_are_shortened() -> None:
    days = [f"202011{day:02d}" for day in range(1, 16)]
    assert rc._listed(days).endswith("and 5 more")
    assert rc._listed(days[:2]) == "20201101, 20201102"


def test_main_fails_on_empty_manifest(
    loader_env: ExtractedData,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    monkeypatch.setenv("RAW_DATA_DIR", str(tmp_path_factory.mktemp("empty")))
    assert rc.main([], connection=FakeSnowflake()) == 1


def test_main_reports_driver_errors(
    loader_env: ExtractedData, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def reject(*_args: object, **_kwargs: object) -> None:
        raise ProgrammingError(msg="Object does not exist or not authorized", errno=2003)

    monkeypatch.setattr(rc, "fetch_counts", reject)
    assert rc.main([], connection=FakeSnowflake()) == 1
    assert "not authorized" in capsys.readouterr().err
