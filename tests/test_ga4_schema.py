from pathlib import Path

import pyarrow as pa
import pytest

from extract_load.ga4_schema import GA4_EVENTS_SCHEMA, SELECTED_COLUMNS, partition_path

NESTED_COLUMNS = (
    "event_params",
    "user_properties",
    "items",
    "ecommerce",
    "device",
    "geo",
    "traffic_source",
)


def test_selected_columns_follow_schema_order() -> None:
    assert tuple(GA4_EVENTS_SCHEMA.names) == SELECTED_COLUMNS
    assert len(set(SELECTED_COLUMNS)) == len(SELECTED_COLUMNS)


@pytest.mark.parametrize("column", NESTED_COLUMNS)
def test_nested_columns_stay_nested(column: str) -> None:
    field_type = GA4_EVENTS_SCHEMA.field(column).type
    assert pa.types.is_list(field_type) or pa.types.is_struct(field_type)


def test_event_param_value_has_all_typed_slots() -> None:
    param_type = GA4_EVENTS_SCHEMA.field("event_params").type.value_type
    value_type = param_type.field("value").type
    assert [value_type.field(i).name for i in range(value_type.num_fields)] == [
        "string_value",
        "int_value",
        "float_value",
        "double_value",
    ]


def test_timestamps_are_integer_microseconds() -> None:
    for column in ("event_timestamp", "user_first_touch_timestamp"):
        assert GA4_EVENTS_SCHEMA.field(column).type == pa.int64()


def test_partition_path_layout(tmp_path: Path) -> None:
    assert partition_path(tmp_path, "20201101") == (
        tmp_path / "event_date=20201101" / "part-0.parquet"
    )


@pytest.mark.parametrize("bad_date", ["2020-11-01", "202011", "2020110a", ""])
def test_partition_path_rejects_bad_dates(tmp_path: Path, bad_date: str) -> None:
    with pytest.raises(ValueError, match="YYYYMMDD"):
        partition_path(tmp_path, bad_date)
