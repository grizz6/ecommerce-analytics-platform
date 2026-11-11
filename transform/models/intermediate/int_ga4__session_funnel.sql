{#
    One row per session with a flag and the first timestamp for each purchase
    funnel step: view_item, add_to_cart, begin_checkout, add_shipping_info,
    add_payment_info and purchase. Steps are recorded as they were logged:
    GA4 does not guarantee that a purchase has its earlier steps, so a
    session can reach a later step without an earlier one.
#}

with

events as (

    select
        session_key,
        event_name,
        event_ts_utc
    from {{ ref('stg_ga4__events') }}
    where session_key is not null

),

sessions as (

    select session_key
    from {{ ref('int_ga4__sessions') }}

),

first_step_times as (

    select
        session_key,
        min(case when event_name = 'view_item' then event_ts_utc end)
            as first_view_item_ts_utc,
        min(case when event_name = 'add_to_cart' then event_ts_utc end)
            as first_add_to_cart_ts_utc,
        min(case when event_name = 'begin_checkout' then event_ts_utc end)
            as first_begin_checkout_ts_utc,
        min(case when event_name = 'add_shipping_info' then event_ts_utc end)
            as first_add_shipping_info_ts_utc,
        min(case when event_name = 'add_payment_info' then event_ts_utc end)
            as first_add_payment_info_ts_utc,
        min(case when event_name = 'purchase' then event_ts_utc end)
            as first_purchase_ts_utc
    from events
    group by session_key

),

final as (

    select
        sessions.session_key,
        first_step_times.first_view_item_ts_utc,
        first_step_times.first_add_to_cart_ts_utc,
        first_step_times.first_begin_checkout_ts_utc,
        first_step_times.first_add_shipping_info_ts_utc,
        first_step_times.first_add_payment_info_ts_utc,
        first_step_times.first_purchase_ts_utc,
        first_step_times.first_view_item_ts_utc is not null as has_view_item,
        first_step_times.first_add_to_cart_ts_utc is not null as has_add_to_cart,
        first_step_times.first_begin_checkout_ts_utc is not null as has_begin_checkout,
        first_step_times.first_add_shipping_info_ts_utc is not null as has_add_shipping_info,
        first_step_times.first_add_payment_info_ts_utc is not null as has_add_payment_info,
        first_step_times.first_purchase_ts_utc is not null as has_purchase
    from sessions
    left join first_step_times
        on sessions.session_key = first_step_times.session_key

)

select * from final
