{#
    One row per order. Duplicate transaction ids are collapsed to one order
    and purchases without a valid transaction id are kept as their own orders
    (see int_ga4__orders). Users appear only as a hashed user_key.
#}

with

orders as (

    select
        order_key,
        transaction_id,
        has_valid_transaction_id,
        purchase_event_count,
        user_pseudo_id,
        session_key,
        order_ts_utc,
        order_date,
        revenue_usd,
        tax_usd,
        shipping_usd,
        item_quantity,
        unique_items
    from {{ ref('int_ga4__orders') }}

),

sessions as (

    select
        session_key,
        device_category,
        geo_country,
        session_channel_group
    from {{ ref('int_ga4__sessions') }}

),

final as (

    select
        cast(orders.order_key as varchar) as order_key,
        cast(orders.transaction_id as varchar) as transaction_id,
        cast(orders.has_valid_transaction_id as boolean) as has_valid_transaction_id,
        cast(orders.purchase_event_count as bigint) as purchase_event_count,
        cast(orders.session_key as varchar) as session_key,
        cast({{ hash_identifier('orders.user_pseudo_id') }} as varchar) as user_key,
        cast(orders.order_ts_utc as timestamp) as order_ts_utc,
        cast(orders.order_date as date) as order_date,
        cast(orders.revenue_usd as double) as revenue_usd,
        cast(orders.tax_usd as double) as tax_usd,
        cast(orders.shipping_usd as double) as shipping_usd,
        cast(orders.item_quantity as bigint) as item_quantity,
        cast(orders.unique_items as bigint) as unique_items,
        cast(sessions.device_category as varchar) as device_category,
        cast(sessions.geo_country as varchar) as geo_country,
        cast(sessions.session_channel_group as varchar) as session_channel_group
    from orders
    left join sessions
        on orders.session_key = sessions.session_key

)

select * from final
