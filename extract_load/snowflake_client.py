"""Snowflake connection settings and key-pair sign-in for the loader.

Every connection value comes from an environment variable. Nothing here logs
those values: errors name the variable that is wrong, never its contents.
The driver's own sign-in messages are shown only after the account
identifier, any Snowflake address and the home directory are redacted.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from extract_load.config import ConfigError

DEFAULT_LOADER_USER = "LOADER_SVC"
DEFAULT_LOADER_ROLE = "LOADER"
DEFAULT_LOADER_WAREHOUSE = "LOADING_WH"
DEFAULT_RAW_DATABASE = "RAW"
DEFAULT_PRIVATE_KEY_PATH = Path("~/.snowflake/keys/loader_svc.p8")
RAW_SCHEMA = "GA4"
EVENTS_TABLE = "EVENTS"
EVENTS_STAGE = "EVENTS_STAGE"
PARQUET_FORMAT = "PARQUET_FORMAT"
APPLICATION_NAME = "ecommerce_analytics_loader"
LOGIN_TIMEOUT_SECONDS = 60

DRIVER_LOGGERS = ("snowflake", "botocore", "boto3", "urllib3")

# The driver reports almost every sign-in failure as error 250001, so hints are
# chosen from the message text. The first matching fragment wins.
CONNECTION_HINTS: tuple[tuple[str, str], ...] = (
    (
        "authentication failed",
        "The private key could not be used. The passphrase is most likely wrong for "
        "this key file: check it with the command in docs/runbook.md, or create a new "
        "key ('Rotate a key').",
    ),
    (
        "jwt",
        "Snowflake rejected the key. The public key on the user does not match this "
        "private key ('Rotate a key' in docs/runbook.md).",
    ),
    (
        "does not exist or not authorized",
        "Check that the service user exists and that SNOWFLAKE_LOADER_USER is right.",
    ),
    (
        "http request failed",
        "Snowflake could not be reached. Check that SNOWFLAKE_ACCOUNT is "
        "ORGNAME-ACCOUNTNAME (a hyphen, no dots, no '.snowflakecomputing.com') and "
        "that no proxy variable is set.",
    ),
    ("timed out", "The connection timed out. Check your network and any proxy settings."),
)
DEFAULT_CONNECTION_HINT = "Check the account identifier, user, key and passphrase."
SNOWFLAKE_ADDRESS = re.compile(r"(https?://)?[\w.-]*snowflakecomputing\.com[^\s'\"]*", re.I)


class SnowflakeError(RuntimeError):
    """Raised for connection or load failures, with a message safe to log."""


class Cursor(Protocol):
    """The part of a DB-API cursor this project uses."""

    description: Any

    def execute(self, command: str, params: Any = ...) -> Any: ...  # noqa: ANN401

    def fetchall(self) -> list[tuple[Any, ...]]: ...

    def close(self) -> Any: ...  # noqa: ANN401


class Connection(Protocol):
    """The part of a DB-API connection this project uses."""

    def cursor(self) -> Cursor: ...

    def close(self) -> Any: ...  # noqa: ANN401


def _get(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value or None


def _required(env: Mapping[str, str], name: str) -> str:
    value = _get(env, name)
    if value is None:
        msg = f"{name} must be set"
        raise ConfigError(msg)
    return value


@dataclass(frozen=True)
class SnowflakeSettings:
    """Connection settings for the loader service user."""

    account: str = field(repr=False)
    user: str
    role: str
    warehouse: str
    database: str
    private_key_path: Path
    private_key_passphrase: str = field(repr=False)

    @classmethod
    def for_loader(cls, env: Mapping[str, str] | None = None) -> SnowflakeSettings:
        source = os.environ if env is None else env
        key_path = Path(
            _get(source, "SNOWFLAKE_LOADER_PRIVATE_KEY_PATH") or DEFAULT_PRIVATE_KEY_PATH
        ).expanduser()
        settings = cls(
            account=_required(source, "SNOWFLAKE_ACCOUNT"),
            user=_get(source, "SNOWFLAKE_LOADER_USER") or DEFAULT_LOADER_USER,
            role=_get(source, "SNOWFLAKE_LOADER_ROLE") or DEFAULT_LOADER_ROLE,
            warehouse=_get(source, "SNOWFLAKE_LOADER_WAREHOUSE") or DEFAULT_LOADER_WAREHOUSE,
            database=_get(source, "SNOWFLAKE_RAW_DATABASE") or DEFAULT_RAW_DATABASE,
            private_key_path=key_path,
            private_key_passphrase=_required(source, "SNOWFLAKE_LOADER_PRIVATE_KEY_PASSPHRASE"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.private_key_path.is_file():
            msg = "The private key file set by SNOWFLAKE_LOADER_PRIVATE_KEY_PATH was not found"
            raise ConfigError(msg)
        if self.private_key_path.stat().st_mode & 0o077:
            msg = (
                "The private key file is readable by other users. "
                "Restrict it with: chmod 600 <path to the key>"
            )
            raise ConfigError(msg)

    @property
    def events_table(self) -> str:
        return f"{self.database}.{RAW_SCHEMA}.{EVENTS_TABLE}"

    @property
    def events_stage(self) -> str:
        return f"@{self.database}.{RAW_SCHEMA}.{EVENTS_STAGE}"

    @property
    def parquet_format(self) -> str:
        return f"{self.database}.{RAW_SCHEMA}.{PARQUET_FORMAT}"


class _DriverLogFilter(logging.Filter):
    """Drop driver log records below ERROR, whatever level the driver sets itself.

    The driver's warnings (proxy detection, cloud region lookups) are noise for
    this tool. Failures still surface through our own error messages.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        from_driver = any(
            record.name == name or record.name.startswith(f"{name}.") for name in DRIVER_LOGGERS
        )
        return not from_driver or record.levelno >= logging.ERROR


def quiet_driver_logs() -> None:
    """Keep driver chatter off the console so connection details never reach it.

    Must run before the driver is imported, because it logs during import.
    Setting logger levels alone is not enough, because the driver sets levels
    on its own child loggers. A filter on every root handler catches all of them.
    """
    for name in DRIVER_LOGGERS:
        logging.getLogger(name).setLevel(logging.ERROR)
    for handler in logging.getLogger().handlers:
        if not any(isinstance(existing, _DriverLogFilter) for existing in handler.filters):
            handler.addFilter(_DriverLogFilter())


def redact_local_paths(text: str) -> str:
    """Replace the home directory, which contains the username, with ~."""
    return text.replace(str(Path.home()), "~")


def redact_connection_details(text: str, account: str) -> str:
    """Remove the account identifier, Snowflake addresses and the home directory."""
    text = SNOWFLAKE_ADDRESS.sub("<snowflake address>", text)
    if account:
        text = re.sub(re.escape(account), "<account>", text, flags=re.IGNORECASE)
    return redact_local_paths(text).strip().rstrip(".")


def connection_hint(reason: str) -> str:
    """Pick the most specific hint for a sign-in failure message."""
    lowered = reason.lower()
    for fragment, hint in CONNECTION_HINTS:
        if fragment in lowered:
            return hint
    return DEFAULT_CONNECTION_HINT


def connect(settings: SnowflakeSettings) -> Connection:
    """Open a key-pair authenticated connection as the configured service user."""
    quiet_driver_logs()
    import snowflake.connector  # noqa: PLC0415 - optional dependency group
    from snowflake.connector.errors import Error as DriverError  # noqa: PLC0415

    try:
        return snowflake.connector.connect(
            account=settings.account,
            user=settings.user,
            authenticator="SNOWFLAKE_JWT",
            private_key_file=str(settings.private_key_path),
            private_key_file_pwd=settings.private_key_passphrase,
            role=settings.role,
            warehouse=settings.warehouse,
            database=settings.database,
            schema=RAW_SCHEMA,
            application=APPLICATION_NAME,
            login_timeout=LOGIN_TIMEOUT_SECONDS,
            client_session_keep_alive=False,
            # No asynchronous queries are used, so always log out cleanly on close.
            enable_server_session_keep_alive_auto_detection=False,
        )
    except DriverError as exc:
        reason = redact_connection_details(
            getattr(exc, "raw_msg", None) or str(exc), settings.account
        )
        msg = (
            f"Could not connect to Snowflake (driver error {exc.errno}): {reason}. "
            f"{connection_hint(reason)}"
        )
        raise SnowflakeError(msg) from None
    except (ValueError, TypeError) as exc:
        # Raised when the key cannot be decrypted, for example a wrong passphrase.
        msg = f"Could not read the private key ({type(exc).__name__}). Check the passphrase."
        raise SnowflakeError(msg) from None


def describe_driver_error(exc: BaseException) -> str:
    """Describe a driver error without leaking connection details.

    SQL errors (for example an object that does not exist) carry useful text
    and no connection details, so their message is shown. Every other driver
    error is reported by type and error code only, because network errors can
    include the account URL.
    """
    try:
        from snowflake.connector.errors import ProgrammingError  # noqa: PLC0415
    except ImportError:  # pragma: no cover - the load group is always installed with this module
        ProgrammingError = ()  # noqa: N806
    errno = getattr(exc, "errno", None)
    if isinstance(exc, ProgrammingError):
        # raw_msg is the message without the error code the driver prefixes to msg.
        message = getattr(exc, "raw_msg", None) or getattr(exc, "msg", None) or "SQL error"
        return f"Snowflake rejected a statement (error {errno}): {redact_local_paths(message)}"
    return f"Snowflake operation failed ({type(exc).__name__}, error {errno})"


def column_index(cursor: Cursor, name: str) -> int:
    """Return the position of a result column, matched case-insensitively."""
    names = [str(column[0]).lower() for column in cursor.description or []]
    try:
        return names.index(name.lower())
    except ValueError as exc:
        msg = f"Result has no column named {name}"
        raise SnowflakeError(msg) from exc
