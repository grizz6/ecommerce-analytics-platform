from datetime import date
from pathlib import Path

import pytest

from extract_load.config import (
    DEFAULT_MAX_BYTES_PER_QUERY,
    DEFAULT_MAX_BYTES_PER_RUN,
    GA4_FIRST_DATE,
    GA4_LAST_DATE,
    ConfigError,
    ExtractSettings,
)


def test_defaults_when_environment_is_empty() -> None:
    settings = ExtractSettings.from_env({})
    assert settings.project_id is None
    assert settings.max_bytes_per_query == DEFAULT_MAX_BYTES_PER_QUERY
    assert settings.max_bytes_per_run == DEFAULT_MAX_BYTES_PER_RUN
    assert (settings.first_date, settings.last_date) == (GA4_FIRST_DATE, GA4_LAST_DATE)
    assert settings.raw_data_dir == Path("data/raw/ga4")


def test_blank_values_fall_back_to_defaults() -> None:
    settings = ExtractSettings.from_env({"GCP_PROJECT_ID": "  ", "BQ_MAX_BYTES_PER_QUERY": ""})
    assert settings.project_id is None
    assert settings.max_bytes_per_query == DEFAULT_MAX_BYTES_PER_QUERY


def test_reads_values_from_environment() -> None:
    settings = ExtractSettings.from_env(
        {
            "GCP_PROJECT_ID": "example-project",
            "BQ_MAX_BYTES_PER_QUERY": "1_000_000",
            "BQ_MAX_BYTES_PER_RUN": "5000000",
            "GA4_START_DATE": "2020-12-01",
            "GA4_END_DATE": "2020-12-31",
            "RAW_DATA_DIR": "/tmp/raw",  # noqa: S108 - path value only, nothing is written
        }
    )
    assert settings.require_project() == "example-project"
    assert settings.max_bytes_per_query == 1_000_000
    assert settings.max_bytes_per_run == 5_000_000
    assert settings.first_date == date(2020, 12, 1)
    assert settings.last_date == date(2020, 12, 31)
    assert settings.raw_data_dir == Path("/tmp/raw")  # noqa: S108


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"BQ_MAX_BYTES_PER_QUERY": "lots"}, "whole number"),
        ({"BQ_MAX_BYTES_PER_QUERY": "0"}, "greater than zero"),
        ({"GA4_START_DATE": "01/11/2020"}, "YYYY-MM-DD"),
        ({"GA4_START_DATE": "2020-12-02", "GA4_END_DATE": "2020-12-01"}, "not be before"),
        ({"GA4_START_DATE": "2020-10-31"}, "must fall within"),
        ({"GA4_END_DATE": "2021-02-01"}, "must fall within"),
        (
            {"BQ_MAX_BYTES_PER_QUERY": "10", "BQ_MAX_BYTES_PER_RUN": "5"},
            "at least BQ_MAX_BYTES_PER_QUERY",
        ),
    ],
)
def test_invalid_values_are_rejected(env: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        ExtractSettings.from_env(env)


def test_error_messages_never_include_the_value() -> None:
    with pytest.raises(ConfigError) as caught:
        ExtractSettings.from_env({"BQ_MAX_BYTES_PER_QUERY": "secret-looking-value"})
    assert "secret-looking-value" not in str(caught.value)


def test_require_project_fails_without_project() -> None:
    with pytest.raises(ConfigError, match="GCP_PROJECT_ID"):
        ExtractSettings.from_env({}).require_project()
