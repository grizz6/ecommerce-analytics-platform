import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import snowflake.connector
from snowflake.connector.errors import DatabaseError, OperationalError, ProgrammingError

from extract_load.config import ConfigError
from extract_load.logging_utils import configure_logging
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
        assert logging.getLogger(name).level == logging.ERROR


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


def test_connect_disables_session_keep_alive_detection(
    key_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(snowflake.connector, "connect", lambda **kwargs: captured.update(kwargs))
    connect(SnowflakeSettings.for_loader(_env(key_file)))
    assert captured["enable_server_session_keep_alive_auto_detection"] is False


def test_driver_noise_is_filtered_even_on_child_loggers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging("INFO")
    child = logging.getLogger("snowflake.connector._core")
    child.setLevel(logging.INFO)  # the driver sets its own child logger levels
    quiet_driver_logs()
    quiet_driver_logs()  # calling twice must not stack filters

    child.info("pyarrow is installed")
    child.warning("failed to load region from IMDS")
    child.error("a real driver error")
    logging.getLogger("extract_load.test").info("our own message")

    logged = capsys.readouterr().err
    assert "pyarrow is installed" not in logged
    assert "IMDS" not in logged
    assert "a real driver error" in logged
    assert "our own message" in logged
    root_handler = logging.getLogger().handlers[0]
    assert sum(type(f).__name__ == "_DriverLogFilter" for f in root_handler.filters) == 1


def test_driver_import_logs_are_hidden_in_a_fresh_process() -> None:
    # The driver logs while it is imported, so the filter must be in place first.
    # A fresh interpreter reproduces a real run, where the driver is not yet loaded.
    script = (
        "from extract_load.logging_utils import configure_logging\n"
        "from extract_load.snowflake_client import quiet_driver_logs\n"
        "configure_logging('INFO')\n"
        "quiet_driver_logs()\n"
        "import snowflake.connector\n"
        "import logging\n"
        "logging.getLogger('extract_load').info('still visible')\n"
    )
    result = subprocess.run(  # noqa: S603 - fixed arguments, current interpreter
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert "still visible" in result.stderr
    assert "snowflake.connector" not in result.stderr


@pytest.mark.parametrize(
    ("driver_message", "expected_hint"),
    [
        # Messages as raised by snowflake-connector-python 5.2.0, all with errno 250001.
        ("Failed to login: Authentication failed. Unspecified", "passphrase is most likely wrong"),
        ("Failed to login: JWT token is invalid.", "does not match this private key"),
        (
            "Failed to login: User 'LOADER_SVC' does not exist or not authorized.",
            "service user exists",
        ),
        (
            "Failed to login: HTTP request failed after retries: login request. tunnel error",
            "could not be reached",
        ),
        ("Something unexpected", "Check the account identifier, user, key and passphrase."),
    ],
)
def test_connection_errors_show_the_reason_and_a_matching_hint(
    key_file: Path, monkeypatch: pytest.MonkeyPatch, driver_message: str, expected_hint: str
) -> None:
    def failing_connect(**_kwargs: Any) -> None:
        raise DatabaseError(msg=driver_message, errno=250001, sqlstate="08001")

    monkeypatch.setattr(snowflake.connector, "connect", failing_connect)
    with pytest.raises(SnowflakeError) as caught:
        connect(SnowflakeSettings.for_loader(_env(key_file)))
    message = str(caught.value)
    assert "driver error 250001" in message
    assert driver_message.rstrip(".") in message
    assert expected_hint in message


def test_connection_errors_redact_account_and_addresses(
    key_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_connect(**_kwargs: Any) -> None:
        raise DatabaseError(
            msg=(
                f"Failed to login: HTTP request failed for https://{ACCOUNT.upper()}"
                f".snowflakecomputing.com:443/session (account {ACCOUNT}) "
                f"using key {Path.home()}/keys/loader_svc.p8"
            ),
            errno=250001,
        )

    monkeypatch.setattr(snowflake.connector, "connect", failing_connect)
    with pytest.raises(SnowflakeError) as caught:
        connect(SnowflakeSettings.for_loader(_env(key_file)))
    message = str(caught.value)
    assert ACCOUNT.lower() not in message.lower()
    # The hint itself mentions the domain; the real address must not appear.
    assert "snowflakecomputing.com:443" not in message
    assert str(Path.home()) not in message
    assert "<snowflake address>" in message
    assert "<account>" in message
    assert "~/keys/loader_svc.p8" in message


def test_sql_error_messages_hide_the_home_directory() -> None:
    message = f"Failed to upload files. File does not exist: {Path.home()}/code/part-0.parquet"
    described = describe_driver_error(ProgrammingError(msg=message, errno=253006))
    assert str(Path.home()) not in described
    assert "~/code/part-0.parquet" in described
