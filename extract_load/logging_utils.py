"""Logging setup shared by every command-line entry point."""

from __future__ import annotations

import logging
import os

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DEFAULT_LEVEL = "INFO"


def resolve_log_level(level: str | None = None) -> str:
    """Return a valid logging level name from the argument, LOG_LEVEL, or the default."""
    candidate = (level or os.environ.get("LOG_LEVEL") or DEFAULT_LEVEL).strip().upper()
    if candidate not in logging.getLevelNamesMapping():
        msg = f"Unknown log level: {candidate!r}"
        raise ValueError(msg)
    return candidate


def configure_logging(level: str | None = None) -> None:
    """Configure the root logger once per process."""
    logging.basicConfig(level=resolve_log_level(level), format=LOG_FORMAT, force=True)
