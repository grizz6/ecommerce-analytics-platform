"""Fail when a dbt model, seed or column has no description.

Reads target/manifest.json (written by dbt parse, build or docs generate) and
reports every project model or seed, and every column of those, whose
description is empty. Exit status is 1 when anything is missing.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from extract_load.logging_utils import configure_logging

logger = logging.getLogger(__name__)

DEFAULT_MANIFEST = Path("transform/target/manifest.json")
PROJECT_NAME = "ecommerce_analytics"
DOCUMENTED_TYPES = ("model", "seed")


def find_undocumented(manifest: dict[str, Any], project: str = PROJECT_NAME) -> list[str]:
    """Return 'node' or 'node.column' names that have no description."""
    missing: list[str] = []
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") not in DOCUMENTED_TYPES or node.get("package_name") != project:
            continue
        name = node["name"]
        if not (node.get("description") or "").strip():
            missing.append(name)
        missing.extend(
            f"{name}.{column_name}"
            for column_name, column in node.get("columns", {}).items()
            if not (column.get("description") or "").strip()
        )
    return sorted(missing)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)
    configure_logging()
    if not args.manifest.is_file():
        logger.error("Manifest not found at %s; run dbt parse first", args.manifest)
        return 1
    missing = find_undocumented(json.loads(args.manifest.read_text()))
    for item in missing:
        logger.error("Missing description: %s", item)
    if missing:
        logger.error("%d item(s) without a description", len(missing))
        return 1
    logger.info("Every model, seed and column is documented")
    return 0


if __name__ == "__main__":
    sys.exit(main())
