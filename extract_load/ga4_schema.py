"""Arrow schema and file layout for the extracted GA4 events.

The schema covers only the columns this project reads from the GA4 BigQuery
export. It was checked field by field against the live definition of
bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_20201101 (a
metadata-only lookup that processes zero bytes). The extractor and the
synthetic fixtures both use this one definition.

Points worth knowing about the obfuscated sample:

- user_properties.key and three of its value slots, plus device.vendor_id,
  device.advertising_id and device.mobile_os_hardware_model, are typed
  INTEGER. In the standard GA4 export they are strings. The obfuscation
  blanked these fields, so the types are kept exactly as published.
- traffic_source fields are ordered medium, name, source.

Columns in the export that no model uses are not extracted: privacy_info,
user_ltv, app_info, stream_id, event_dimensions and
event_server_timestamp_offset. Leaving them out also lowers the bytes each
query processes.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

PARTITION_KEY = "event_date"
PARTITION_FILE_NAME = "part-0.parquet"
EVENT_DATE_FORMAT = "%Y%m%d"


EVENT_PARAM_TYPE = pa.struct(
    [
        ("key", pa.string()),
        (
            "value",
            pa.struct(
                [
                    ("string_value", pa.string()),
                    ("int_value", pa.int64()),
                    ("float_value", pa.float64()),
                    ("double_value", pa.float64()),
                ]
            ),
        ),
    ]
)

# Every field is INTEGER in the obfuscated sample; see the module docstring.
USER_PROPERTY_TYPE = pa.struct(
    [
        ("key", pa.int64()),
        (
            "value",
            pa.struct(
                [
                    ("string_value", pa.int64()),
                    ("int_value", pa.int64()),
                    ("float_value", pa.int64()),
                    ("double_value", pa.int64()),
                    ("set_timestamp_micros", pa.int64()),
                ]
            ),
        ),
    ]
)

DEVICE_TYPE = pa.struct(
    [
        ("category", pa.string()),
        ("mobile_brand_name", pa.string()),
        ("mobile_model_name", pa.string()),
        ("mobile_marketing_name", pa.string()),
        ("mobile_os_hardware_model", pa.int64()),
        ("operating_system", pa.string()),
        ("operating_system_version", pa.string()),
        ("vendor_id", pa.int64()),
        ("advertising_id", pa.int64()),
        ("language", pa.string()),
        ("is_limited_ad_tracking", pa.string()),
        ("time_zone_offset_seconds", pa.int64()),
        ("web_info", pa.struct([("browser", pa.string()), ("browser_version", pa.string())])),
    ]
)

GEO_TYPE = pa.struct(
    [
        ("continent", pa.string()),
        ("sub_continent", pa.string()),
        ("country", pa.string()),
        ("region", pa.string()),
        ("city", pa.string()),
        ("metro", pa.string()),
    ]
)

TRAFFIC_SOURCE_TYPE = pa.struct(
    [("medium", pa.string()), ("name", pa.string()), ("source", pa.string())]
)

ECOMMERCE_TYPE = pa.struct(
    [
        ("total_item_quantity", pa.int64()),
        ("purchase_revenue_in_usd", pa.float64()),
        ("purchase_revenue", pa.float64()),
        ("refund_value_in_usd", pa.float64()),
        ("refund_value", pa.float64()),
        ("shipping_value_in_usd", pa.float64()),
        ("shipping_value", pa.float64()),
        ("tax_value_in_usd", pa.float64()),
        ("tax_value", pa.float64()),
        ("unique_items", pa.int64()),
        ("transaction_id", pa.string()),
    ]
)

ITEM_TYPE = pa.struct(
    [
        ("item_id", pa.string()),
        ("item_name", pa.string()),
        ("item_brand", pa.string()),
        ("item_variant", pa.string()),
        ("item_category", pa.string()),
        ("item_category2", pa.string()),
        ("item_category3", pa.string()),
        ("item_category4", pa.string()),
        ("item_category5", pa.string()),
        ("price_in_usd", pa.float64()),
        ("price", pa.float64()),
        ("quantity", pa.int64()),
        ("item_revenue_in_usd", pa.float64()),
        ("item_revenue", pa.float64()),
        ("item_refund_in_usd", pa.float64()),
        ("item_refund", pa.float64()),
        ("coupon", pa.string()),
        ("affiliation", pa.string()),
        ("location_id", pa.string()),
        ("item_list_id", pa.string()),
        ("item_list_name", pa.string()),
        ("item_list_index", pa.string()),
        ("promotion_id", pa.string()),
        ("promotion_name", pa.string()),
        ("creative_name", pa.string()),
        ("creative_slot", pa.string()),
    ]
)

GA4_EVENTS_SCHEMA = pa.schema(
    [
        ("event_date", pa.string()),
        ("event_timestamp", pa.int64()),
        ("event_name", pa.string()),
        ("event_params", pa.list_(EVENT_PARAM_TYPE)),
        ("event_previous_timestamp", pa.int64()),
        ("event_value_in_usd", pa.float64()),
        ("event_bundle_sequence_id", pa.int64()),
        ("user_id", pa.string()),
        ("user_pseudo_id", pa.string()),
        ("user_properties", pa.list_(USER_PROPERTY_TYPE)),
        ("user_first_touch_timestamp", pa.int64()),
        ("device", DEVICE_TYPE),
        ("geo", GEO_TYPE),
        ("traffic_source", TRAFFIC_SOURCE_TYPE),
        ("platform", pa.string()),
        ("ecommerce", ECOMMERCE_TYPE),
        ("items", pa.list_(ITEM_TYPE)),
    ]
)

SELECTED_COLUMNS: tuple[str, ...] = tuple(GA4_EVENTS_SCHEMA.names)


def partition_path(root: Path, event_date: str) -> Path:
    """Return the Parquet file path for one day, for example root/event_date=20201101/."""
    if len(event_date) != len("YYYYMMDD") or not event_date.isdigit():
        msg = f"event_date must look like YYYYMMDD, got {event_date!r}"
        raise ValueError(msg)
    return root / f"{PARTITION_KEY}={event_date}" / PARTITION_FILE_NAME
