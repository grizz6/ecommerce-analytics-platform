"""Keep the Airflow image's library versions in step with pyproject.toml.

The Airflow image installs dbt and the extract/load libraries into their own
virtual environments from orchestration/include/requirements-*.txt. These
tests fail if a version there drifts from the version the rest of the
project is tested with.
"""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENT_FILES = sorted((ROOT / "orchestration" / "include").glob("requirements-*.txt"))
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s#]+)")


def _pins(lines: list[str]) -> dict[str, str]:
    pins = {}
    for line in lines:
        match = PIN.match(line.strip())
        if match:
            pins[match.group(1).lower()] = match.group(2)
    return pins


def _project_pins() -> dict[str, str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lines = list(data["project"]["dependencies"])
    for group in data["dependency-groups"].values():
        lines.extend(group)
    return _pins(lines)


def test_requirement_files_exist() -> None:
    assert [path.name for path in REQUIREMENT_FILES] == [
        "requirements-dbt.txt",
        "requirements-extract-load.txt",
    ]


@pytest.mark.parametrize("path", REQUIREMENT_FILES, ids=lambda path: path.name)
def test_image_pins_match_pyproject(path: Path) -> None:
    image_pins = _pins(path.read_text().splitlines())
    project_pins = _project_pins()
    assert image_pins, f"{path.name} has no pinned packages"
    for package, version in image_pins.items():
        assert package in project_pins, f"{package} is not pinned in pyproject.toml"
        assert version == project_pins[package], (
            f"{package}: {path.name} pins {version}, pyproject.toml pins {project_pins[package]}"
        )
