"""Write orchestration/.env for local Airflow runs, asking for secrets at a hidden prompt.

Airflow runs unattended, so it reads its settings from orchestration/.env
instead of the current shell. This script builds that file:

- the Google Cloud project comes from the gcloud configuration;
- the Snowflake account identifier and both key passphrases are typed at
  hidden prompts and never echoed or logged;
- paths point at the read-only mounts in docker-compose.override.yml;
- the dbt Snowflake connection is written as Airflow connection JSON.

The file is created with owner-only permissions (600) and is gitignored.
"""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from extract_load.logging_utils import configure_logging

logger = logging.getLogger(__name__)

DEFAULT_ENV_PATH = Path("orchestration/.env")
CONTAINER_PROJECT = "/usr/local/airflow/project"
CONTAINER_KEYS = "/usr/local/airflow/keys"
ACCOUNT_PATTERN = re.compile(r"^[A-Za-z0-9_]+-[A-Za-z0-9_]+$")


class EnvFileError(ValueError):
    """Raised when an entered value cannot be written safely."""


def _check_value(name: str, value: str) -> str:
    if not value:
        msg = f"{name} cannot be empty"
        raise EnvFileError(msg)
    # Values are single-quoted in the env file, so a quote or a line break
    # would end the value early.
    if "'" in value or "\n" in value or "\r" in value:
        msg = f"{name} cannot contain a single quote or a line break"
        raise EnvFileError(msg)
    return value


def build_env(
    gcp_project_id: str, account: str, loader_passphrase: str, dbt_passphrase: str
) -> dict[str, str]:
    """Return the settings for orchestration/.env."""
    _check_value("GCP project id", gcp_project_id)
    _check_value("Snowflake account identifier", account)
    if not ACCOUNT_PATTERN.match(account):
        msg = "The Snowflake account identifier must look like ORGNAME-ACCOUNTNAME"
        raise EnvFileError(msg)
    _check_value("Loader key passphrase", loader_passphrase)
    _check_value("dbt key passphrase", dbt_passphrase)
    dbt_connection = {
        "conn_type": "snowflake",
        "login": "DBT_SVC",
        "password": dbt_passphrase,
        "schema": "ANALYTICS",
        "extra": {
            "account": account,
            "database": "ANALYTICS",
            "warehouse": "TRANSFORMING_WH",
            "role": "TRANSFORMER",
            "private_key_file": f"{CONTAINER_KEYS}/dbt_svc.p8",
        },
    }
    return {
        "PYTHONPATH": CONTAINER_PROJECT,
        "PROJECT_ROOT": CONTAINER_PROJECT,
        "RAW_DATA_DIR": f"{CONTAINER_PROJECT}/data/raw/ga4",
        "GCP_PROJECT_ID": gcp_project_id,
        "GOOGLE_APPLICATION_CREDENTIALS": "/usr/local/airflow/gcloud/adc.json",
        "SNOWFLAKE_ACCOUNT": account,
        "SNOWFLAKE_LOADER_PRIVATE_KEY_PATH": f"{CONTAINER_KEYS}/loader_svc.p8",
        "SNOWFLAKE_LOADER_PRIVATE_KEY_PASSPHRASE": loader_passphrase,
        "AIRFLOW_CONN_SNOWFLAKE_DBT": json.dumps(dbt_connection, separators=(",", ":")),
    }


def render_env(values: dict[str, str]) -> str:
    """Render settings as an env file with single-quoted values."""
    lines = [
        "# Written by scripts/write_airflow_env.py. Contains secrets: never commit or share.",
        *(f"{key}='{value}'" for key, value in values.items()),
    ]
    return "\n".join(lines) + "\n"


def write_env_file(path: Path, content: str) -> None:
    """Write the file so that only the owner can read it, from the moment it exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(content)
    path.chmod(0o600)


def gcloud_project() -> str:
    """Read the active project from the gcloud configuration."""
    try:
        result = subprocess.run(
            ["gcloud", "config", "get-value", "project"],  # noqa: S607 - user's gcloud on PATH
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        msg = "Could not read the project from gcloud; run 'gcloud config set project' first"
        raise EnvFileError(msg) from exc
    return result.stdout.strip()


def main(
    argv: Sequence[str] | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
    project_reader: Callable[[], str] = gcloud_project,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=DEFAULT_ENV_PATH)
    args = parser.parse_args(argv)
    configure_logging()
    try:
        values = build_env(
            gcp_project_id=project_reader(),
            account=prompt("Snowflake account identifier (ORGNAME-ACCOUNTNAME): ").strip(),
            loader_passphrase=prompt("Loader key passphrase: "),
            dbt_passphrase=prompt("dbt key passphrase: "),
        )
    except EnvFileError as exc:
        logger.error("%s", exc)
        return 1
    write_env_file(args.output, render_env(values))
    logger.info("Wrote %s with owner-only permissions", args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
