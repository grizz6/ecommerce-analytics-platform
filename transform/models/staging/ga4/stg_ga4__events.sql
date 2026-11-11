{#
    One row per GA4 event, typed and deduplicated.

    Snowflake: incremental. Each run reprocesses the latest loaded GA4 dates
    minus var('event_lookback_days') and merges on event_key, so reloaded or
    late-arriving days replace their rows instead of duplicating them.
    DuckDB: rebuilt as a table every run; the CI fixtures are small.
#}
{{
    config(
        materialized='incremental' if target.type == 'snowflake' else 'table',
        unique_key='event_key',
        incremental_strategy='merge',
        on_schema_change='append_new_columns',
    )
}}

with

source_events as (

    select * from {{ source('ga4', 'events') }}

    {% if is_incremental() %}
        where
            event_date >= (
                select
                    to_varchar(
                        dateadd(day, -{{ var('event_lookback_days') }}, max(event_date)),
                        'YYYYMMDD'
                    )
                from {{ this }}
            )
    {% endif %}

),

keyed as (

    select
        -- The export has no event identifier. Exact duplicate rows exist, so
        -- the key fingerprints the event, including all of its parameters.
        {{ dbt_utils.generate_surrogate_key([
            'user_pseudo_id',
            'event_timestamp',
            'event_name',
            'event_bundle_sequence_id',
            nested_as_json('event_params'),
        ]) }} as event_key,
        *
    from source_events

),

deduplicated as (

    select *
    from keyed
    qualify
        row_number() over (
            partition by event_key
            order by _loaded_at, _source_file
        ) = 1

),

typed as (

    select
        event_key,

        -- When
        {{ parse_yyyymmdd('event_date') }} as event_date,
        {{ micros_to_timestamp('event_timestamp') }} as event_ts_utc,
        cast(
            {{ to_reporting_time(micros_to_timestamp('event_timestamp')) }} as date
        ) as reporting_date,
        {{ to_reporting_time(micros_to_timestamp('event_timestamp')) }} as event_ts_local,
        event_timestamp as event_timestamp_micros,
        event_bundle_sequence_id,

        -- What and who
        event_name,
        user_pseudo_id,
        user_id,
        {{ micros_to_timestamp('user_first_touch_timestamp') }} as user_first_touch_ts_utc,

        -- Session
        {{ event_param('ga_session_id', 'int_value') }} as ga_session_id,
        {{ event_param('ga_session_number', 'int_value') }} as ga_session_number,

        -- Page
        {{ event_param('page_location') }} as page_location,
        {{ event_param('page_title') }} as page_title,
        {{ event_param('page_referrer') }} as page_referrer,
        coalesce({{ event_param('entrances', 'int_value') }} = 1, false) as is_entrance,
        {{ event_param('engagement_time_msec', 'int_value') }} as engagement_time_msec,
        coalesce({{ event_param_as_string('session_engaged') }} = '1', false) as is_session_engaged,

        -- Event-level traffic attribution, used for session source
        {{ event_param('source') }} as event_source,
        {{ event_param('medium') }} as event_medium,
        {{ event_param('campaign') }} as event_campaign,

        -- User-level first-touch attribution (traffic_source record)
        {{ nested_field('traffic_source', 'source') }} as first_touch_source,
        {{ nested_field('traffic_source', 'medium') }} as first_touch_medium,
        {{ nested_field('traffic_source', 'name') }} as first_touch_campaign,

        -- Device and location
        {{ nested_field('device', 'category') }} as device_category,
        {{ nested_field('device', 'operating_system') }} as device_operating_system,
        {{ nested_field('device', 'web_info.browser') }} as device_browser,
        {{ nested_field('device', 'language') }} as device_language,
        {{ nested_field('geo', 'continent') }} as geo_continent,
        {{ nested_field('geo', 'sub_continent') }} as geo_sub_continent,
        {{ nested_field('geo', 'country') }} as geo_country,
        {{ nested_field('geo', 'region') }} as geo_region,
        {{ nested_field('geo', 'city') }} as geo_city,
        platform,

        -- E-commerce
        {{ nested_field('ecommerce', 'transaction_id') }} as transaction_id,
        {{ nested_field('ecommerce', 'purchase_revenue_in_usd', 'double') }}
            as purchase_revenue_usd,
        {{ nested_field('ecommerce', 'tax_value_in_usd', 'double') }} as tax_value_usd,
        {{ nested_field('ecommerce', 'shipping_value_in_usd', 'double') }}
            as shipping_value_usd,
        {{ nested_field('ecommerce', 'refund_value_in_usd', 'double') }} as refund_value_usd,
        {{ nested_field('ecommerce', 'total_item_quantity', 'bigint') }}
            as total_item_quantity,
        {{ nested_field('ecommerce', 'unique_items', 'bigint') }} as unique_items,
        event_value_in_usd,
        {{ array_length('items') }} as item_count,

        -- Nested fields kept for the long-format staging models
        event_params,
        items,

        -- Load metadata
        _source_file,
        _loaded_at

    from deduplicated

),

final as (

    select
        typed.*,
        -- A session is identified by user and GA4 session id together. Events
        -- without a session id have no session key.
        case
            when typed.ga_session_id is not null
                then
                    {{ dbt_utils.generate_surrogate_key([
                        'typed.user_pseudo_id', 'typed.ga_session_id'
                    ]) }}
        end as session_key
    from typed

)

select * from final
