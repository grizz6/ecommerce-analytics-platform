import logging

import pytest

from extract_load.logging_utils import configure_logging, resolve_log_level


def test_resolve_log_level_prefers_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert resolve_log_level("debug") == "DEBUG"


def test_resolve_log_level_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "warning")
    assert resolve_log_level() == "WARNING"


def test_resolve_log_level_defaults_to_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    assert resolve_log_level() == "INFO"


def test_resolve_log_level_rejects_unknown_level() -> None:
    with pytest.raises(ValueError, match="Unknown log level"):
        resolve_log_level("chatty")


def test_configure_logging_sets_root_level() -> None:
    configure_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING
