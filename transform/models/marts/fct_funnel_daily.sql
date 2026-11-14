{#
    Purchase funnel per day, device and channel, on complete reporting days.

    Step counts are a closed funnel: a session counts at a step only if it
    also logged every earlier step. That keeps each step conversion between
    0 and 1. GA4 does not guarantee earlier steps are logged, so some
    purchasing sessions skip steps; they still count in purchase_sessions_any
    and in overall conversion, which matches kpi_daily.
#}

with

sessions as (

    select
        session_key,
        session_date,
        device_category,
        session_channel_group
    from {{ ref('int_ga4__sessions') }}

),

funnel as (

    select
        session_key,
        has_view_item,
        has_add_to_cart,
        has_begin_checkout,
        has_add_shipping_info,
        has_add_payment_info,
        has_purchase
    from {{ ref('int_ga4__session_funnel') }}

),

complete_days as (

    select date_day
    from {{ ref('dim_date') }}
    where is_complete_reporting_day

),

session_steps as (

    select
        sessions.session_date,
        sessions.session_channel_group,
        funnel.has_purchase,
        funnel.has_view_item as reached_view_item,
        coalesce(sessions.device_category, '(not set)') as device_category,
        funnel.has_view_item and funnel.has_add_to_cart as reached_add_to_cart,
        funnel.has_view_item and funnel.has_add_to_cart and funnel.has_begin_checkout
            as reached_begin_checkout,
        funnel.has_view_item and funnel.has_add_to_cart and funnel.has_begin_checkout
        and funnel.has_add_shipping_info as reached_add_shipping_info,
        funnel.has_view_item and funnel.has_add_to_cart and funnel.has_begin_checkout
        and funnel.has_add_shipping_info and funnel.has_add_payment_info
            as reached_add_payment_info,
        funnel.has_view_item and funnel.has_add_to_cart and funnel.has_begin_checkout
        and funnel.has_add_shipping_info and funnel.has_add_payment_info
        and funnel.has_purchase as reached_purchase
    from sessions
    inner join funnel
        on sessions.session_key = funnel.session_key
    inner join complete_days
        on sessions.session_date = complete_days.date_day

),

aggregated as (

    select
        session_date,
        device_category,
        session_channel_group,
        count(*) as sessions,
        sum(case when reached_view_item then 1 else 0 end) as view_item_sessions,
        sum(case when reached_add_to_cart then 1 else 0 end) as add_to_cart_sessions,
        sum(case when reached_begin_checkout then 1 else 0 end) as begin_checkout_sessions,
        sum(case when reached_add_shipping_info then 1 else 0 end)
            as add_shipping_info_sessions,
        sum(case when reached_add_payment_info then 1 else 0 end) as add_payment_info_sessions,
        sum(case when reached_purchase then 1 else 0 end) as purchase_sessions,
        sum(case when has_purchase then 1 else 0 end) as purchase_sessions_any
    from session_steps
    group by session_date, device_category, session_channel_group

),

final as (

    select
        cast(session_date as date) as session_date,
        cast(device_category as varchar) as device_category,
        cast(session_channel_group as varchar) as session_channel_group,
        cast(sessions as bigint) as sessions,
        cast(view_item_sessions as bigint) as view_item_sessions,
        cast(add_to_cart_sessions as bigint) as add_to_cart_sessions,
        cast(begin_checkout_sessions as bigint) as begin_checkout_sessions,
        cast(add_shipping_info_sessions as bigint) as add_shipping_info_sessions,
        cast(add_payment_info_sessions as bigint) as add_payment_info_sessions,
        cast(purchase_sessions as bigint) as purchase_sessions,
        cast(purchase_sessions_any as bigint) as purchase_sessions_any,
        cast({{ safe_divide('view_item_sessions', 'sessions') }} as double)
            as view_item_rate,
        cast({{ safe_divide('add_to_cart_sessions', 'view_item_sessions') }} as double)
            as add_to_cart_rate,
        cast({{ safe_divide('begin_checkout_sessions', 'add_to_cart_sessions') }} as double)
            as begin_checkout_rate,
        cast({{ safe_divide('add_shipping_info_sessions', 'begin_checkout_sessions') }} as double)
            as add_shipping_info_rate,
        cast({{ safe_divide('add_payment_info_sessions', 'add_shipping_info_sessions') }} as double)
            as add_payment_info_rate,
        cast({{ safe_divide('purchase_sessions', 'add_payment_info_sessions') }} as double)
            as purchase_rate,
        cast({{ safe_divide('purchase_sessions_any', 'sessions') }} as double)
            as overall_conversion_rate
    from aggregated

)

select * from final
