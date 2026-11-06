import logging
from pathlib import Path
from typing import Any

import pytest
import snowflake.connector
from snowflake.connector.errors import OperationalError, ProgrammingError

from extract_load.config import ConfigError
from extract_load.snowflake_client import (
    DRIVER_LOGGERS,
    SnowflakeError,
    SnowflakeSettings,
    column_index,
    connect,
    describe_driver_error,
    quiet_driver_logs,
)
from tests.conftest import ACCOUNT, PASSPHRASE


def _env(key_file: Path, **overrides: str) -> dict[str, str]:
    env = {
        "SNOWFLAKE_ACCOUNT": ACCOUNT,
        "SNOWFLAKE_LOADER_PRIVATE_KEY_PATH": str(key_file),
        "SNOWFLAKE_LOADER_PRIVATE_KEY_PASSPHRASE": PASSPHRASE,
    }
    env.update(overrides)
    return env


def test_defaults_match_the_setup_scripts(key_file: Path) -> None:
    settings = SnowflakeSettings.for_loader(_env(key_file))
    assert (settings.user, settings.role, settings.warehouse, settings.database) == (
        "LOADER_SVC",
        "LOADER",
        "LOADING_WH",
        "RAW",
    )
    assert settings.events_table == "RAW.GA4.EVENTS"
    assert settings.events_stage == "@RAW.GA4.EVENTS_STAGE"
    assert settings.parquet_format == "RAW.GA4.PARQUET_FORMAT"


def test_overrides_are_read(key_file: Path) -> None:
    settings = SnowflakeSettings.for_loader(
        _env(key_file, SNOWFLAKE_LOADER_USER="OTHER_SVC", SNOWFLAKE_RAW_DATABASE="RAW_DEV")
    )
    assert settings.user == "OTHER_SVC"
    assert settings.events_table == "RAW_DEV.GA4.EVENTS"


@pytest.mark.parametrize(
    "missing", ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_LOADER_PRIVATE_KEY_PASSPHRASE"]
)
def test_required_values(key_file: Path, missing: str) -> None:
    env = _env(key_file)
    env[missing] = " "
    with pytest.raises(ConfigError, match=missing):
        SnowflakeSettings.for_loader(env)


def test_missing_key_file_is_rejected(tmp_path: Path, key_file: Path) -> None:
    env = _env(key_file, SNOWFLAKE_LOADER_PRIVATE_KEY_PATH=str(tmp_path / "absent.p8"))
    with pytest.raises(ConfigError, match="not found"):
        SnowflakeSettings.for_loader(env)


def test_key_readable_by_others_is_rejected(key_file: Path) -> None:
    key_file.chmod(0o644)
    with pytest.raises(ConfigError, match="chmod 600"):
        SnowflakeSettings.for_loader(_env(key_file))


def test_repr_hides_account_and_passphrase(key_file: Path) -> None:
    text = repr(SnowflakeSettings.for_loader(_env(key_file)))
    assert ACCOUNT not in text
    assert PASSPHRASE not in text


def test_connect_uses_key_pair_only(key_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_connect(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "connection"

    monkeypatch.setattr(snowflake.connector, "connect", fake_connect)
    assert connect(SnowflakeSettings.for_loader(_env(key_file))) == "connection"
    assert captured["authenticator"] == "SNOWFLAKE_JWT"
    assert captured["private_key_file"] == str(key_file)
    assert captured["private_key_file_pwd"] == PASSPHRASE
    assert "password" not in captured
    assert (captured["role"], captured["warehouse"], captured["schema"]) == (
        "LOADER",
        "LOADING_WH",
        "GA4",
    )


def test_connection_errors_hide_details(key_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_connect(**_kwargs: Any) -> None:
        raise OperationalError(
            msg=f"Failed to connect to {ACCOUNT}.snowflakecomputing.com", errno=250001
        )

    monkeypatch.setattr(snowflake.connector, "connect", failing_connect)
    with pytest.raises(SnowflakeError) as caught:
        connect(SnowflakeSettings.for_loader(_env(key_file)))
    assert "250001" in str(caught.value)
    assert ACCOUNT not in str(caught.value)
    assert caught.value.__cause__ is None


def test_bad_passphrase_is_explained(key_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_connect(**_kwargs: Any) -> None:
        raise ValueError("Bad decrypt. Incorrect password?")

    monkeypatch.setattr(snowflake.connector, "connect", failing_connect)
    with pytest.raises(SnowflakeError, match="passphrase"):
        connect(SnowflakeSettings.for_loader(_env(key_file)))


def test_quiet_driver_logs() -> None:
    logging.getLogger("snowflake").setLevel(logging.DEBUG)
    quiet_driver_logs()
    for name in DRIVER_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


def test_describe_driver_error_shows_sql_errors_only() -> None:
    sql_error = ProgrammingError(msg="Object 'RAW.GA4.EVENTS' does not exist", errno=2003)
    assert describe_driver_error(sql_error) == (
        "Snowflake rejected a statement (error 2003): Object 'RAW.GA4.EVENTS' does not exist"
    )
    network_error = OperationalError(msg=f"timeout talking to {ACCOUNT}", errno=250003)
    described = describe_driver_error(network_error)
    assert "250003" in described
    assert ACCOUNT not in described


class _DescribedCursor:
    description = (("FILE",), ("ROWS_LOADED",))


def test_column_index_is_case_insensitive() -> None:
    assert column_index(_DescribedCursor(), "rows_loaded") == 1  # type: ignore[arg-type]
    with pytest.raises(SnowflakeError, match="no column"):
        column_index(_DescribedCursor(), "missing")  # type: ignore[arg-type]
