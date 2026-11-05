"""Generate synthetic GA4 export data for CI and local development.

The output uses the same layout as the BigQuery extractor:
<output_dir>/event_date=YYYYMMDD/part-0.parquet, one file per day.

Every value is generated from a seeded random number generator, so the same
arguments always produce the same rows. Nothing is derived from real data.

The data deliberately includes the awkward cases the dbt models must handle:
exact duplicate events, purchases with a missing or repeated transaction ID,
purchases with no earlier funnel steps, events without a session ID, and the
"(data deleted)", "<Other>" and empty-string placeholders found in the public
obfuscated sample.
"""

from __future__ import annotations

import argparse
import logging
import random
import re
import shutil
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

from extract_load.ga4_schema import (
    EVENT_DATE_FORMAT,
    GA4_EVENTS_SCHEMA,
    PARTITION_KEY,
    partition_path,
)
from extract_load.logging_utils import configure_logging

logger = logging.getLogger(__name__)

DEFAULT_SEED = 20201101
DEFAULT_USERS = 600
MIN_USERS = 100
DEFAULT_START = date(2020, 11, 1)
DEFAULT_END = date(2020, 12, 13)
DEFAULT_OUTPUT_DIR = Path("data/fixtures/ga4")
# Synthetic choice. The real property timezone is confirmed during extraction.
DEFAULT_PROPERTY_TIMEZONE = "America/Los_Angeles"

SITE = "https://shop.example-store.test"
MICROS = 1_000_000
MAX_SESSIONS_PER_USER = 8
PARTITION_DIR_PATTERN = re.compile(rf"^{PARTITION_KEY}=\d{{8}}$")

# Each edge case is applied to users whose index satisfies index % modulus == remainder.
PURCHASE_WITHOUT_FUNNEL = (37, 5)
MISSING_TRANSACTION_ID = (53, 7)
NOT_SET_TRANSACTION_ID = (59, 11)
DUPLICATE_TRANSACTION_ID = (61, 13)
MISSING_SESSION_ID = (71, 17)
DUPLICATE_ROW_EVERY = 97
FORCED_PURCHASE_RULES = (
    PURCHASE_WITHOUT_FUNNEL,
    MISSING_TRANSACTION_ID,
    NOT_SET_TRANSACTION_ID,
    DUPLICATE_TRANSACTION_ID,
)
# Users who carry an edge case get their first visit at least this long before the window ends.
EDGE_CASE_HEADROOM_US = 24 * 3600 * 1_000_000

FUNNEL_STEPS: tuple[tuple[str, float], ...] = (
    ("view_item", 0.55),
    ("add_to_cart", 0.40),
    ("begin_checkout", 0.60),
    ("add_shipping_info", 0.85),
    ("add_payment_info", 0.85),
    ("purchase", 0.80),
)


@dataclass(frozen=True)
class TrafficProfile:
    """Traffic attributes as they appear in the export."""

    source: str
    medium: str
    campaign: str
    referrer: str
    weight: int


@dataclass(frozen=True)
class DeviceProfile:
    """Device attributes for one user."""

    category: str
    operating_system: str
    browser: str
    language: str
    weight: int


@dataclass(frozen=True)
class GeoProfile:
    """Location attributes for one user."""

    continent: str
    sub_continent: str
    country: str
    region: str
    city: str
    weight: int


@dataclass(frozen=True)
class Product:
    """A synthetic catalogue item."""

    item_id: str
    item_name: str
    item_category: str
    price: float


DIRECT = TrafficProfile("(direct)", "(none)", "(direct)", "", 0)

TRAFFIC_PROFILES: tuple[TrafficProfile, ...] = (
    TrafficProfile("google", "organic", "(organic)", "https://www.google.com/", 30),
    TrafficProfile("(direct)", "(none)", "(direct)", "", 22),
    TrafficProfile("google", "cpc", "holiday_promo", "https://www.google.com/", 9),
    TrafficProfile("newsletter", "email", "monthly_newsletter", "", 5),
    TrafficProfile("partner-blog.test", "referral", "(referral)", "https://partner-blog.test/", 7),
    TrafficProfile("facebook.com", "referral", "(referral)", "https://facebook.com/", 4),
    TrafficProfile("youtube.com", "referral", "(referral)", "https://youtube.com/", 3),
    TrafficProfile("<Other>", "<Other>", "<Other>", "", 8),
    TrafficProfile("(data deleted)", "(data deleted)", "(data deleted)", "", 8),
    TrafficProfile("", "", "", "", 4),
)

DEVICE_PROFILES: tuple[DeviceProfile, ...] = (
    DeviceProfile("desktop", "Windows", "Chrome", "en-us", 34),
    DeviceProfile("desktop", "Macintosh", "Safari", "en-us", 12),
    DeviceProfile("desktop", "Macintosh", "Chrome", "en-gb", 8),
    DeviceProfile("mobile", "iOS", "Safari", "en-us", 20),
    DeviceProfile("mobile", "Android", "Chrome", "en-us", 17),
    DeviceProfile("tablet", "iOS", "Safari", "en-us", 5),
    DeviceProfile("mobile", "<Other>", "<Other>", "<Other>", 4),
)

GEO_PROFILES: tuple[GeoProfile, ...] = (
    GeoProfile("Americas", "Northern America", "United States", "California", "San Jose", 25),
    GeoProfile("Americas", "Northern America", "United States", "New York", "New York", 15),
    GeoProfile("Americas", "Northern America", "United States", "Texas", "Austin", 8),
    GeoProfile("Americas", "Northern America", "Canada", "Ontario", "Toronto", 8),
    GeoProfile("Asia", "Southern Asia", "India", "Karnataka", "Bengaluru", 10),
    GeoProfile("Europe", "Northern Europe", "United Kingdom", "England", "London", 9),
    GeoProfile("Europe", "Western Europe", "Germany", "Berlin", "Berlin", 5),
    GeoProfile("Americas", "Northern America", "United States", "(data deleted)", "", 12),
    GeoProfile("(not set)", "(not set)", "(not set)", "(not set)", "(not set)", 8),
)

PRODUCTS: tuple[Product, ...] = (
    Product("SKU1001", "Classic Logo Tee", "Apparel", 22.0),
    Product("SKU1002", "Zip Hoodie", "Apparel", 48.0),
    Product("SKU1003", "Knit Beanie", "Apparel", 18.0),
    Product("SKU2001", "Insulated Water Bottle", "Drinkware", 26.0),
    Product("SKU2002", "Ceramic Mug", "Drinkware", 14.0),
    Product("SKU3001", "Canvas Tote", "Bags", 19.0),
    Product("SKU3002", "Everyday Backpack", "Bags", 65.0),
    Product("SKU4001", "Sticker Sheet", "Stationery", 4.0),
    Product("SKU4002", "Ruled Notebook", "Stationery", 9.0),
    Product("SKU5001", "Phone Stand", "Accessories", 15.0),
    Product("SKU5002", "Enamel Pin Set", "Accessories", 11.0),
    Product("(not set)", "(not set)", "(not set)", 12.0),
)

ParamBuilder = Callable[[str, str], list[dict[str, Any]]]

PAGES: tuple[tuple[str, str], ...] = (
    ("/", "Home"),
    ("/apparel", "Apparel"),
    ("/drinkware", "Drinkware"),
    ("/bags", "Bags"),
    ("/stationery", "Stationery"),
    ("/sale", "Sale"),
)


@dataclass(frozen=True)
class FixtureConfig:
    """Inputs that fully determine the generated data."""

    seed: int = DEFAULT_SEED
    users: int = DEFAULT_USERS
    start: date = DEFAULT_START
    end: date = DEFAULT_END
    property_timezone: str = DEFAULT_PROPERTY_TIMEZONE

    def validate(self) -> None:
        """Reject inputs that would silently drop the edge cases."""
        if self.users < MIN_USERS:
            msg = f"users must be at least {MIN_USERS} so every edge case is generated"
            raise ValueError(msg)
        if self.end < self.start:
            msg = "end date must not be before start date"
            raise ValueError(msg)
        ZoneInfo(self.property_timezone)


def _param(key: str, value: str | int | float) -> dict[str, Any]:
    """Build one event_params entry with only the matching value field set."""
    typed: dict[str, Any] = {
        "string_value": None,
        "int_value": None,
        "float_value": None,
        "double_value": None,
    }
    if isinstance(value, str):
        typed["string_value"] = value
    elif isinstance(value, int):
        typed["int_value"] = value
    else:
        typed["double_value"] = value
    return {"key": key, "value": typed}


def _item(product: Product, quantity: int, *, purchased: bool) -> dict[str, Any]:
    revenue = round(product.price * quantity, 2) if purchased else None
    return {
        "item_id": product.item_id,
        "item_name": product.item_name,
        "item_brand": "Example Store",
        "item_variant": "(not set)",
        "item_category": product.item_category,
        "item_category2": "",
        "item_category3": "",
        "item_category4": "",
        "item_category5": "",
        "price_in_usd": product.price,
        "price": product.price,
        "quantity": quantity,
        "item_revenue_in_usd": revenue,
        "item_revenue": revenue,
        "item_refund_in_usd": None,
        "item_refund": None,
        "coupon": "(not set)",
        "affiliation": "(not set)",
        "location_id": None,
        "item_list_id": "(not set)",
        "item_list_name": "(not set)",
        "item_list_index": "(not set)",
        "promotion_id": "(not set)",
        "promotion_name": "(not set)",
        "creative_name": "(not set)",
        "creative_slot": "(not set)",
    }


def _purchase_ecommerce(items: list[dict[str, Any]], transaction_id: str | None) -> dict[str, Any]:
    subtotal = round(sum(item["item_revenue"] for item in items), 2)
    tax = round(subtotal * 0.08, 2)
    shipping = 0.0 if subtotal >= 50 else 7.99  # noqa: PLR2004 - free shipping threshold
    revenue = round(subtotal + tax + shipping, 2)
    return {
        "total_item_quantity": sum(item["quantity"] for item in items),
        "purchase_revenue_in_usd": revenue,
        "purchase_revenue": revenue,
        "refund_value_in_usd": None,
        "refund_value": None,
        "shipping_value_in_usd": shipping,
        "shipping_value": shipping,
        "tax_value_in_usd": tax,
        "tax_value": tax,
        "unique_items": len(items),
        "transaction_id": transaction_id,
    }


def _matches(index: int, rule: tuple[int, int]) -> bool:
    modulus, remainder = rule
    return index % modulus == remainder


def has_forced_purchase(index: int) -> bool:
    """Return True for users whose first session must end in a purchase edge case."""
    return any(_matches(index, rule) for rule in FORCED_PURCHASE_RULES)


@dataclass(frozen=True)
class _UserSeed:
    """Identity and timing for one synthetic user."""

    index: int
    user_pseudo_id: str
    first_visit_us: int
    window_end_us: int


class _UserSimulator:
    """Builds every event for one synthetic user."""

    def __init__(self, rng: random.Random, seed: _UserSeed, counters: dict[str, int]) -> None:
        self.rng = rng
        self.index = seed.index
        self.user_pseudo_id = seed.user_pseudo_id
        self.first_visit_us = seed.first_visit_us
        self.window_end_us = seed.window_end_us
        self.counters = counters
        self.device = rng.choices(DEVICE_PROFILES, [d.weight for d in DEVICE_PROFILES])[0]
        self.geo = rng.choices(GEO_PROFILES, [g.weight for g in GEO_PROFILES])[0]
        self.acquisition = rng.choices(TRAFFIC_PROFILES, [t.weight for t in TRAFFIC_PROFILES])[0]
        self.rows: list[dict[str, Any]] = []
        self.purchase_count = 0

    def _next_bundle_id(self) -> int:
        self.counters["bundle"] += 1
        return self.counters["bundle"]

    def _next_transaction_id(self) -> str:
        self.counters["transaction"] += 1
        return f"T{self.counters['transaction']:06d}"

    def _row(
        self,
        event_name: str,
        timestamp_us: int,
        params: list[dict[str, Any]],
        *,
        items: list[dict[str, Any]] | None = None,
        ecommerce: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        revenue = ecommerce["purchase_revenue_in_usd"] if event_name == "purchase" else None
        return {
            "event_timestamp": timestamp_us,
            "event_name": event_name,
            "event_params": params,
            "event_previous_timestamp": None,
            "event_value_in_usd": revenue,
            "event_bundle_sequence_id": self._next_bundle_id(),
            "user_id": None,
            "user_pseudo_id": self.user_pseudo_id,
            "user_properties": [],
            "user_first_touch_timestamp": self.first_visit_us,
            "device": {
                "category": self.device.category,
                "mobile_brand_name": None,
                "mobile_model_name": None,
                "mobile_marketing_name": None,
                "mobile_os_hardware_model": None,
                "operating_system": self.device.operating_system,
                "operating_system_version": None,
                "vendor_id": None,
                "advertising_id": None,
                "language": self.device.language,
                "is_limited_ad_tracking": "No",
                "time_zone_offset_seconds": None,
                "web_info": {"browser": self.device.browser, "browser_version": None},
            },
            "geo": {
                "continent": self.geo.continent,
                "sub_continent": self.geo.sub_continent,
                "country": self.geo.country,
                "region": self.geo.region,
                "city": self.geo.city,
                "metro": "(not set)",
            },
            "traffic_source": {
                "name": self.acquisition.campaign,
                "medium": self.acquisition.medium,
                "source": self.acquisition.source,
            },
            "platform": "WEB",
            "ecommerce": ecommerce,
            "items": items or [],
        }

    def _session_traffic(self, session_number: int) -> TrafficProfile:
        if session_number == 1:
            return self.acquisition
        if self.rng.random() < 0.55:  # noqa: PLR2004 - share of returning visits that are direct
            return DIRECT
        return self.rng.choices(TRAFFIC_PROFILES, [t.weight for t in TRAFFIC_PROFILES])[0]

    def simulate(self) -> list[dict[str, Any]]:
        session_start_us = self.first_visit_us
        session_number = 1
        while session_start_us <= self.window_end_us and session_number <= MAX_SESSIONS_PER_USER:
            self._simulate_session(session_number, session_start_us)
            if self.rng.random() >= 0.45:  # noqa: PLR2004 - chance of another session
                break
            gap_hours = self.rng.uniform(2, 24 * 14)
            session_start_us += int(gap_hours * 3600 * MICROS)
            session_number += 1
        return [row for row in self.rows if row["event_timestamp"] <= self.window_end_us]

    def _simulate_session(self, session_number: int, start_us: int) -> None:
        rng = self.rng
        traffic = self._session_traffic(session_number)
        forced = session_number == 1 and has_forced_purchase(self.index)
        engaged = forced or rng.random() < 0.62  # noqa: PLR2004 - engaged session rate
        session_id = start_us // MICROS
        drop_session_id = session_number == 1 and _matches(self.index, MISSING_SESSION_ID)
        page_path, page_title = rng.choice(PAGES)

        def base_params(path: str, title: str) -> list[dict[str, Any]]:
            params = [
                _param("ga_session_number", session_number),
                _param("page_location", f"{SITE}{path}"),
                _param("page_title", title),
            ]
            if not drop_session_id:
                params.insert(0, _param("ga_session_id", session_id))
            if engaged:
                params.append(_param("session_engaged", "1"))
                params.append(_param("engaged_session_event", 1))
            return params

        traffic_params = [
            _param("source", traffic.source),
            _param("medium", traffic.medium),
            _param("campaign", traffic.campaign),
        ]
        landing_params = [
            *base_params(page_path, page_title),
            *traffic_params,
            _param("entrances", 1),
            _param("page_referrer", traffic.referrer),
        ]

        t = start_us
        if session_number == 1:
            self.rows.append(self._row("first_visit", t, base_params(page_path, page_title)))
        self.rows.append(self._row("session_start", t, [*base_params(page_path, page_title)]))
        t += rng.randint(100_000, 900_000)
        self.rows.append(self._row("page_view", t, landing_params))

        if not engaged:
            return

        for _ in range(rng.randint(0, 3)):
            t += rng.randint(5, 90) * MICROS
            path, title = rng.choice(PAGES)
            self.rows.append(self._row("page_view", t, base_params(path, title)))
        if rng.random() < 0.3:  # noqa: PLR2004 - scroll rate
            t += rng.randint(5, 60) * MICROS
            params = [*base_params(page_path, page_title), _param("percent_scrolled", 90)]
            self.rows.append(self._row("scroll", t, params))

        if session_number == 1 and _matches(self.index, PURCHASE_WITHOUT_FUNNEL):
            t = self._purchase(t, base_params("/checkout/confirmation", "Order Confirmation"))
        else:
            t = self._funnel(t, base_params, force_purchase=forced)

        t += rng.randint(5, 30) * MICROS
        params = [
            *base_params(page_path, page_title),
            _param("engagement_time_msec", rng.randint(2_000, 240_000)),
        ]
        self.rows.append(self._row("user_engagement", t, params))

    def _funnel(self, t: int, base_params: ParamBuilder, *, force_purchase: bool) -> int:
        rng = self.rng
        products = rng.sample(PRODUCTS, k=rng.randint(1, 3))
        cart = [(product, rng.randint(1, 3)) for product in products]
        for step, probability in FUNNEL_STEPS:
            if not force_purchase and rng.random() >= probability:
                return t
            t += rng.randint(10, 180) * MICROS
            if step == "purchase":
                return self._purchase(
                    t, base_params("/checkout/confirmation", "Order Confirmation"), cart
                )
            if step == "view_item":
                items = [_item(product, 1, purchased=False) for product, _ in cart]
            else:
                items = [_item(product, qty, purchased=False) for product, qty in cart]
            value = round(sum(item["price"] * item["quantity"] for item in items), 2)
            params = [
                *base_params("/checkout" if "info" in step else "/product", step),
                _param("currency", "USD"),
                _param("value", value),
            ]
            self.rows.append(self._row(step, t, params, items=items))
        return t

    def _purchase(
        self,
        t: int,
        params: list[dict[str, Any]],
        cart: list[tuple[Product, int]] | None = None,
    ) -> int:
        rng = self.rng
        if cart is None:
            cart = [(rng.choice(PRODUCTS), rng.randint(1, 2))]
        items = [_item(product, qty, purchased=True) for product, qty in cart]
        self.purchase_count += 1
        first_purchase = self.purchase_count == 1

        transaction_id: str | None = self._next_transaction_id()
        if first_purchase and _matches(self.index, MISSING_TRANSACTION_ID):
            transaction_id = None
        elif first_purchase and _matches(self.index, NOT_SET_TRANSACTION_ID):
            transaction_id = "(not set)"

        ecommerce = _purchase_ecommerce(items, transaction_id)
        purchase_params = [*params, _param("currency", "USD")]
        if transaction_id is not None:
            purchase_params.append(_param("transaction_id", transaction_id))
        self.rows.append(
            self._row("purchase", t, purchase_params, items=items, ecommerce=ecommerce)
        )

        if first_purchase and _matches(self.index, DUPLICATE_TRANSACTION_ID):
            # The same order is logged again a few seconds later, as happens on page reloads.
            t += rng.randint(2, 8) * MICROS
            self.rows.append(
                self._row("purchase", t, purchase_params, items=items, ecommerce=ecommerce)
            )
        return t


def _window_bounds_us(config: FixtureConfig) -> tuple[int, int]:
    tz = ZoneInfo(config.property_timezone)
    start = datetime.combine(config.start, time.min, tzinfo=tz)
    end = datetime.combine(config.end + timedelta(days=1), time.min, tzinfo=tz)
    return int(start.timestamp() * MICROS), int(end.timestamp() * MICROS) - 1


def generate_events(config: FixtureConfig) -> list[dict[str, Any]]:
    """Return every synthetic event row, already sorted and with event_date set."""
    config.validate()
    rng = random.Random(config.seed)  # noqa: S311 - reproducible test data, not cryptography
    window_start_us, window_end_us = _window_bounds_us(config)
    counters = {"bundle": 0, "transaction": 0}
    seen_ids: set[str] = set()
    rows: list[dict[str, Any]] = []

    for index in range(config.users):
        # Earlier first visits are more likely, so later cohorts are smaller, as on a real site.
        offset_fraction = rng.betavariate(1.0, 1.6)
        latest_first_visit_us = window_end_us
        if has_forced_purchase(index) or _matches(index, MISSING_SESSION_ID):
            latest_first_visit_us -= EDGE_CASE_HEADROOM_US
        span = latest_first_visit_us - window_start_us
        first_visit_us = window_start_us + int(offset_fraction * span)
        user_pseudo_id = f"{rng.randint(10**8, 10**10 - 1)}.{first_visit_us // MICROS}"
        while user_pseudo_id in seen_ids:
            user_pseudo_id = f"{rng.randint(10**8, 10**10 - 1)}.{first_visit_us // MICROS}"
        seen_ids.add(user_pseudo_id)
        seed = _UserSeed(index, user_pseudo_id, first_visit_us, window_end_us)
        simulator = _UserSimulator(rng, seed, counters)
        rows.extend(simulator.simulate())

    duplicates = [dict(row) for pos, row in enumerate(rows) if pos % DUPLICATE_ROW_EVERY == 0]
    rows.extend(duplicates)

    tz = ZoneInfo(config.property_timezone)
    for row in rows:
        local = datetime.fromtimestamp(row["event_timestamp"] / MICROS, tz=tz)
        row["event_date"] = local.strftime(EVENT_DATE_FORMAT)

    rows.sort(
        key=lambda r: (
            r["event_timestamp"],
            r["user_pseudo_id"],
            r["event_name"],
            r["event_bundle_sequence_id"],
        )
    )
    logger.info(
        "Generated %d events (%d exact duplicates) for %d users",
        len(rows),
        len(duplicates),
        config.users,
    )
    return rows


def _clear_partitions(output_dir: Path) -> None:
    """Remove existing day partitions so a rerun leaves no stale days behind."""
    if not output_dir.exists():
        return
    for child in output_dir.iterdir():
        if child.is_dir() and PARTITION_DIR_PATTERN.match(child.name):
            shutil.rmtree(child)


def write_partitions(rows: list[dict[str, Any]], output_dir: Path) -> dict[str, int]:
    """Write one Parquet file per event_date and return the row count per day."""
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_date[row["event_date"]].append(row)

    _clear_partitions(output_dir)
    counts: dict[str, int] = {}
    for event_date in sorted(by_date):
        path = partition_path(output_dir, event_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pylist(by_date[event_date], schema=GA4_EVENTS_SCHEMA)
        pq.write_table(table, path, compression="snappy")
        counts[event_date] = table.num_rows
    logger.info("Wrote %d daily partitions to %s", len(counts), output_dir)
    return counts


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--users", type=int, default=DEFAULT_USERS)
    parser.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    parser.add_argument("--end", type=date.fromisoformat, default=DEFAULT_END)
    parser.add_argument("--property-timezone", default=DEFAULT_PROPERTY_TIMEZONE)
    parser.add_argument("--log-level", default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)
    config = FixtureConfig(
        seed=args.seed,
        users=args.users,
        start=args.start,
        end=args.end,
        property_timezone=args.property_timezone,
    )
    counts = write_partitions(generate_events(config), args.output_dir)
    logger.info("Total rows written: %d", sum(counts.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
