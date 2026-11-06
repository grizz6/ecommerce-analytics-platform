"""Settings for extract and load commands, read from environment variables.

Values are validated here and never logged, so a misconfigured variable fails
fast with a message that names the variable but not its value.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

GA4_DATASET = "bigquery-public-data.ga4_obfuscated_sample_ecommerce"
GA4_TABLE_PREFIX = "events_"
BIGQUERY_LOCATION = "US"

# The 92 daily tables confirmed in the public dataset.
GA4_FIRST_DATE = date(2020, 11, 1)
GA4_LAST_DATE = date(2021, 1, 31)

GIB = 1024**3
DEFAULT_MAX_BYTES_PER_QUERY = 2 * GIB
DEFAULT_MAX_BYTES_PER_RUN = 100 * GIB
DEFAULT_RAW_DATA_DIR = Path("data/raw/ga4")


class ConfigError(ValueError):
    """Raised when an environment variable is missing or invalid."""


def _get(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value or None


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = _get(env, name)
    if raw is None:
        return default
    try:
        value = int(raw.replace("_", ""))
    except ValueError as exc:
        msg = f"{name} must be a whole number of bytes"
        raise ConfigError(msg) from exc
    if value <= 0:
        msg = f"{name} must be greater than zero"
        raise ConfigError(msg)
    return value


def _date(env: Mapping[str, str], name: str, default: date) -> date:
    raw = _get(env, name)
    if raw is None:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        msg = f"{name} must be a date in YYYY-MM-DD format"
        raise ConfigError(msg) from exc


@dataclass(frozen=True)
class ExtractSettings:
    """Everything the BigQuery extractor needs, apart from credentials.

    Credentials come from Application Default Credentials and are never read
    or stored by this code.
    """

    project_id: str | None
    max_bytes_per_query: int
    max_bytes_per_run: int
    first_date: date
    last_date: date
    raw_data_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ExtractSettings:
        source = os.environ if env is None else env
        settings = cls(
            project_id=_get(source, "GCP_PROJECT_ID"),
            max_bytes_per_query=_positive_int(
                source, "BQ_MAX_BYTES_PER_QUERY", DEFAULT_MAX_BYTES_PER_QUERY
            ),
            max_bytes_per_run=_positive_int(
                source, "BQ_MAX_BYTES_PER_RUN", DEFAULT_MAX_BYTES_PER_RUN
            ),
            first_date=_date(source, "GA4_START_DATE", GA4_FIRST_DATE),
            last_date=_date(source, "GA4_END_DATE", GA4_LAST_DATE),
            raw_data_dir=Path(_get(source, "RAW_DATA_DIR") or DEFAULT_RAW_DATA_DIR),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.last_date < self.first_date:
            msg = "GA4_END_DATE must not be before GA4_START_DATE"
            raise ConfigError(msg)
        if self.first_date < GA4_FIRST_DATE or self.last_date > GA4_LAST_DATE:
            msg = (
                "GA4_START_DATE and GA4_END_DATE must fall within "
                f"{GA4_FIRST_DATE.isoformat()} and {GA4_LAST_DATE.isoformat()}"
            )
            raise ConfigError(msg)
        if self.max_bytes_per_run < self.max_bytes_per_query:
            msg = "BQ_MAX_BYTES_PER_RUN must be at least BQ_MAX_BYTES_PER_QUERY"
            raise ConfigError(msg)

    def require_project(self) -> str:
        """Return the project used for query quota, or fail if it is not set."""
        if self.project_id is None:
            msg = "GCP_PROJECT_ID must be set to run BigQuery queries"
            raise ConfigError(msg)
        return self.project_id
