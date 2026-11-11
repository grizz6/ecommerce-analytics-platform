{#
    One row per item per event, for events that carry items (view_item,
    add_to_cart, begin_checkout, purchase and others).
#}

with

events as (

    select
        event_key,
        event_name,
        event_date,
        event_ts_utc,
        reporting_date,
        user_pseudo_id,
        session_key,
        transaction_id,
        items
    from {{ ref('stg_ga4__events') }}
    where item_count > 0

),

flattened as (

    select
        events.event_key,
        events.event_name,
        events.event_date,
        events.event_ts_utc,
        events.reporting_date,
        events.user_pseudo_id,
        events.session_key,
        events.transaction_id,
        {{ flattened_index('item') }} as item_index,
        {{ nested_field(flattened_value('item'), 'item_id') }} as item_id,
        {{ nested_field(flattened_value('item'), 'item_name') }} as item_name,
        {{ nested_field(flattened_value('item'), 'item_brand') }} as item_brand,
        {{ nested_field(flattened_value('item'), 'item_variant') }} as item_variant,
        {{ nested_field(flattened_value('item'), 'item_category') }} as item_category,
        {{ nested_field(flattened_value('item'), 'price_in_usd', 'double') }} as price_usd,
        {{ nested_field(flattened_value('item'), 'quantity', 'bigint') }} as quantity,
        {{ nested_field(flattened_value('item'), 'item_revenue_in_usd', 'double') }}
            as item_revenue_usd,
        {{ nested_field(flattened_value('item'), 'coupon') }} as coupon
    from events,
        {{ flatten_array('events.items', 'item') }}

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['event_key', 'item_index']) }} as event_item_key,
        event_key,
        item_index,
        event_name,
        event_date,
        event_ts_utc,
        reporting_date,
        user_pseudo_id,
        session_key,
        transaction_id,
        item_id,
        item_name,
        item_brand,
        item_variant,
        item_category,
        price_usd,
        quantity,
        item_revenue_usd,
        coupon
    from flattened

)

select * from final
