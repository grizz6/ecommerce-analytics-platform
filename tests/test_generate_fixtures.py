from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq
import pytest

from extract_load.ga4_schema import GA4_EVENTS_SCHEMA
from scripts.generate_fixtures import (
    FixtureConfig,
    generate_events,
    main,
    write_partitions,
)

SMALL = FixtureConfig(seed=7, users=150, start=date(2020, 11, 1), end=date(2020, 11, 28))
FUNNEL_BEFORE_PURCHASE = {
    "view_item",
    "add_to_cart",
    "begin_checkout",
    "add_shipping_info",
    "add_payment_info",
}


@pytest.fixture(scope="module")
def rows() -> list[dict[str, Any]]:
    return generate_events(SMALL)


def _param(row: dict[str, Any], key: str) -> dict[str, Any] | None:
    for param in row["event_params"]:
        if param["key"] == key:
            return param["value"]
    return None


def _session_key(row: dict[str, Any]) -> tuple[str, int] | None:
    value = _param(row, "ga_session_id")
    return None if value is None else (row["user_pseudo_id"], value["int_value"])


def test_same_seed_is_deterministic(rows: list[dict[str, Any]]) -> None:
    assert generate_events(SMALL) == rows


def test_different_seed_changes_data(rows: list[dict[str, Any]]) -> None:
    other = FixtureConfig(seed=8, users=150, start=SMALL.start, end=SMALL.end)
    assert generate_events(other) != rows


def test_events_stay_inside_window(rows: list[dict[str, Any]]) -> None:
    dates = {row["event_date"] for row in rows}
    assert min(dates) >= "20201101"
    assert max(dates) <= "20201128"


def test_event_date_uses_property_timezone(rows: list[dict[str, Any]]) -> None:
    tz = ZoneInfo(SMALL.property_timezone)
    for row in rows[:500]:
        local = datetime.fromtimestamp(row["event_timestamp"] / 1_000_000, tz=tz)
        assert row["event_date"] == local.strftime("%Y%m%d")


def test_rows_match_arrow_schema(rows: list[dict[str, Any]], tmp_path: Path) -> None:
    write_partitions(rows, tmp_path)
    table = pq.read_table(next(tmp_path.glob("event_date=*/part-0.parquet")))
    assert table.schema.equals(GA4_EVENTS_SCHEMA)


def test_has_exact_duplicate_events(rows: list[dict[str, Any]]) -> None:
    keys = Counter(
        (r["user_pseudo_id"], r["event_timestamp"], r["event_name"], r["event_bundle_sequence_id"])
        for r in rows
    )
    assert any(count > 1 for count in keys.values())


def test_has_missing_and_not_set_transaction_ids(rows: list[dict[str, Any]]) -> None:
    purchases = [r for r in rows if r["event_name"] == "purchase"]
    transaction_ids = [p["ecommerce"]["transaction_id"] for p in purchases]
    assert None in transaction_ids
    assert "(not set)" in transaction_ids


def test_has_repeated_transaction_id_at_different_times(rows: list[dict[str, Any]]) -> None:
    timestamps_by_id: dict[str, set[int]] = {}
    for row in rows:
        if row["event_name"] == "purchase" and row["ecommerce"]["transaction_id"]:
            transaction_id = row["ecommerce"]["transaction_id"]
            timestamps_by_id.setdefault(transaction_id, set()).add(row["event_timestamp"])
    assert any(len(ts) > 1 for tid, ts in timestamps_by_id.items() if tid != "(not set)")


def test_has_purchase_without_earlier_funnel_steps(rows: list[dict[str, Any]]) -> None:
    events_by_session: dict[tuple[str, int], set[str]] = {}
    for row in rows:
        key = _session_key(row)
        if key is not None:
            events_by_session.setdefault(key, set()).add(row["event_name"])
    assert any(
        "purchase" in names and not names & FUNNEL_BEFORE_PURCHASE
        for names in events_by_session.values()
    )


def test_has_events_without_session_id(rows: list[dict[str, Any]]) -> None:
    assert any(_session_key(row) is None for row in rows)


def test_has_obfuscation_placeholders(rows: list[dict[str, Any]]) -> None:
    sources = {row["traffic_source"]["source"] for row in rows}
    assert {"(data deleted)", "<Other>", ""} <= sources


def test_covers_every_device_category(rows: list[dict[str, Any]]) -> None:
    assert {row["device"]["category"] for row in rows} == {"desktop", "mobile", "tablet"}


def test_purchase_revenue_is_non_negative_and_consistent(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        if row["event_name"] != "purchase":
            continue
        ecommerce = row["ecommerce"]
        item_total = round(sum(item["item_revenue"] for item in row["items"]), 2)
        expected = round(item_total + ecommerce["tax_value"] + ecommerce["shipping_value"], 2)
        assert ecommerce["purchase_revenue"] >= 0
        assert ecommerce["purchase_revenue"] == pytest.approx(expected)
        assert row["event_value_in_usd"] == ecommerce["purchase_revenue"]


def test_users_return_across_weeks(rows: list[dict[str, Any]]) -> None:
    sessions_per_user: dict[str, set[int]] = {}
    for row in rows:
        value = _param(row, "ga_session_number")
        if value is not None:
            sessions_per_user.setdefault(row["user_pseudo_id"], set()).add(value["int_value"])
    returning = sum(1 for numbers in sessions_per_user.values() if len(numbers) > 1)
    assert returning >= 0.2 * len(sessions_per_user)


def test_write_partitions_is_idempotent(rows: list[dict[str, Any]], tmp_path: Path) -> None:
    stale = tmp_path / "event_date=19990101"
    stale.mkdir()
    (stale / "part-0.parquet").write_bytes(b"stale")
    unrelated = tmp_path / "keep_me"
    unrelated.mkdir()

    first = write_partitions(rows, tmp_path)
    second = write_partitions(rows, tmp_path)

    assert first == second
    assert sum(first.values()) == len(rows)
    assert not stale.exists()
    assert unrelated.exists()
    partitions = sorted(p.name for p in tmp_path.glob("event_date=*"))
    assert partitions == [f"event_date={day}" for day in sorted(first)]


@pytest.mark.parametrize(
    ("config", "message"),
    [
        (FixtureConfig(users=10), "at least"),
        (FixtureConfig(start=date(2020, 12, 2), end=date(2020, 12, 1)), "end date"),
    ],
)
def test_invalid_config_is_rejected(config: FixtureConfig, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        generate_events(config)


def test_main_writes_partitions(tmp_path: Path) -> None:
    exit_code = main(
        [
            "--output-dir",
            str(tmp_path),
            "--users",
            "100",
            "--start",
            "2020-11-01",
            "--end",
            "2020-11-07",
        ]
    )
    assert exit_code == 0
    assert list(tmp_path.glob("event_date=*/part-0.parquet"))
