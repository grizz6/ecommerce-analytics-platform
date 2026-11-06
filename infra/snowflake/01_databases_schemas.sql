-- 01. Databases, schemas, the raw events table, stage and file format.
-- Run after 00_roles_warehouses.sql. Safe to rerun.

use role sysadmin;

-- RAW holds data exactly as extracted. ANALYTICS holds everything dbt builds.
create database if not exists raw
    comment = 'Source data as extracted. Written by LOADER only.';

create schema if not exists raw.ga4
    comment = 'GA4 obfuscated sample e-commerce events.';

create database if not exists analytics
    comment = 'dbt models. Built by TRANSFORMER.';

-- The production marts schema is created here so the REPORTER role can be
-- granted access to it, and only to it, before dbt builds the first model.
create schema if not exists analytics.marts
    comment = 'Published marts. The only schema BI tools can read.';

-- Parquet files are loaded through a named file format and internal stage.
create file format if not exists raw.ga4.parquet_format
    type = parquet
    comment = 'Daily GA4 Parquet files written by the extractor.';

create stage if not exists raw.ga4.events_stage
    file_format = raw.ga4.parquet_format
    comment = 'Internal stage. One folder per day: event_date=YYYYMMDD/.';

-- One row per GA4 event. Nested fields are kept as VARIANT and flattened in
-- dbt. Columns match the Parquet names, so COPY INTO can match by name.
create table if not exists raw.ga4.events (
    event_date varchar not null,
    event_timestamp number(38, 0),
    event_name varchar,
    event_params variant,
    event_previous_timestamp number(38, 0),
    event_value_in_usd float,
    event_bundle_sequence_id number(38, 0),
    user_id varchar,
    user_pseudo_id varchar,
    user_properties variant,
    user_first_touch_timestamp number(38, 0),
    device variant,
    geo variant,
    traffic_source variant,
    platform varchar,
    ecommerce variant,
    items variant,
    _source_file varchar not null,
    _loaded_at timestamp_ltz not null
)
comment = 'Raw GA4 events, one row per event, loaded per day by snowflake_load.py.';

-- TRANSFORMER builds and owns everything in the marts schema.
use role securityadmin;

grant ownership on schema analytics.marts to role transformer copy current grants;
