"""Shared fixtures: a small extracted dataset and loader settings on disk."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pyarrow as pa
import pytest

from extract_load.bigquery_extract import write_day
from extract_load.ga4_schema import GA4_EVENTS_SCHEMA
from scripts.generate_fixtures import FixtureConfig, generate_events

PASSPHRASE = "not-a-real-passphrase"  # noqa: S105 - test value, never a real key
ACCOUNT = "example-account"


@dataclass(frozen=True)
class ExtractedData:
    raw_dir: Path
    manifest: dict[str, dict[str, object]]


@pytest.fixture(scope="session")
def _fixture_rows() -> list[dict[str, object]]:
    config = FixtureConfig(seed=5, users=100, start=date(2020, 11, 1), end=date(2020, 11, 3))
    return generate_events(config)


@pytest.fixture
def extracted(tmp_path: Path, _fixture_rows: list[dict[str, object]]) -> ExtractedData:
    """Three extracted days with a manifest, as the extractor writes them."""
    raw_dir = tmp_path / "raw"
    manifest: dict[str, dict[str, object]] = {}
    for day in ("20201101", "20201102", "20201103"):
        rows = [row for row in _fixture_rows if row["event_date"] == day]
        path = write_day(pa.Table.from_pylist(rows, schema=GA4_EVENTS_SCHEMA), raw_dir, day)
        manifest[day] = {
            "event_date": day,
            "rows": len(rows),
            "file": path.relative_to(raw_dir).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (raw_dir / "_manifest.json").write_text(json.dumps(manifest))
    return ExtractedData(raw_dir=raw_dir, manifest=manifest)


@pytest.fixture
def key_file(tmp_path: Path) -> Path:
    """A stand-in private key file with owner-only permissions."""
    path = tmp_path / "keys" / "loader_svc.p8"
    path.parent.mkdir()
    path.write_text("placeholder, never parsed in tests\n")
    path.chmod(0o600)
    return path


@pytest.fixture
def loader_env(
    monkeypatch: pytest.MonkeyPatch, key_file: Path, extracted: ExtractedData
) -> ExtractedData:
    """Environment variables for the loader, pointing at the test data and key."""
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", ACCOUNT)
    monkeypatch.setenv("SNOWFLAKE_LOADER_PRIVATE_KEY_PATH", str(key_file))
    monkeypatch.setenv("SNOWFLAKE_LOADER_PRIVATE_KEY_PASSPHRASE", PASSPHRASE)
    monkeypatch.setenv("RAW_DATA_DIR", str(extracted.raw_dir))
    for name in ("GA4_START_DATE", "GA4_END_DATE"):
        monkeypatch.delenv(name, raising=False)
    return extracted
