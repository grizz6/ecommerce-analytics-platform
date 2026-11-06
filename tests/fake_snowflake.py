"""An in-memory stand-in for a Snowflake connection, used by the loader tests.

It keeps a per-day row count for RAW.GA4.EVENTS and honours BEGIN, COMMIT and
ROLLBACK, so tests can check idempotency and all-or-nothing behaviour without
a real account.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

COPY_COLUMNS = ("file", "status", "rows_parsed", "rows_loaded", "error_limit", "errors_seen")
DAY_PATTERN = re.compile(r"event_date=(\d{8})")


@dataclass
class FakeSnowflake:
    """Shared state for every cursor opened on one fake connection."""

    rows_per_file: dict[str, int] = field(default_factory=dict)
    table: dict[str, int] = field(default_factory=dict)
    executed: list[tuple[str, Any]] = field(default_factory=list)
    fail_on: str | None = None
    closed: bool = False
    _snapshot: dict[str, int] | None = None

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def close(self) -> None:
        self.closed = True

    @property
    def statements(self) -> list[str]:
        return [sql.split()[0].lower() for sql, _ in self.executed]


@dataclass
class FakeCursor:
    db: FakeSnowflake
    description: list[tuple[str, ...]] | None = None
    _results: list[tuple[Any, ...]] = field(default_factory=list)

    def execute(self, command: str, params: Any = None) -> FakeCursor:
        db = self.db
        db.executed.append((command, params))
        verb = command.split(maxsplit=1)[0].lower()
        if db.fail_on is not None and verb == db.fail_on:
            raise RuntimeError(f"simulated failure on {verb}")
        self.description, self._results = None, []
        if verb == "begin":
            db._snapshot = dict(db.table)
        elif verb == "commit":
            db._snapshot = None
        elif verb == "rollback":
            if db._snapshot is not None:
                db.table = db._snapshot
            db._snapshot = None
        elif verb == "delete":
            db.table.pop(params[0], None)
        elif verb == "copy":
            day = DAY_PATTERN.search(command).group(1)
            loaded = db.rows_per_file.get(day, 0)
            db.table[day] = db.table.get(day, 0) + loaded
            self.description = [(name,) for name in COPY_COLUMNS]
            self._results = [(f"event_date={day}/part-0.parquet", "LOADED", loaded, loaded, 1, 0)]
        elif verb == "select":
            self.description = [("EVENT_DATE",), ("ROW_COUNT",)]
            self._results = sorted(db.table.items())
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._results)

    def close(self) -> None:
        return None
