{#
    One row per order and touchpoint, with the share of the order each
    attribution model gives that touchpoint.

    Touchpoints are the ordering user's sessions that started within
    var('attribution_lookback_days') before the order, up to and including
    the order time. Under every model the credits for one order sum to 1:

    - first touch: the earliest touchpoint gets 1
    - last non-direct touch: the latest touchpoint whose channel is not
      Direct gets 1; if every touchpoint is Direct, the latest one gets 1
    - linear: each touchpoint gets 1 / number of touchpoints

    An order with no touchpoint (not expected, since the order's own session
    always qualifies) keeps a single Unassigned touchpoint so its revenue is
    never lost.
#}

with

orders as (

    select
        order_key,
        user_pseudo_id,
        order_ts_utc,
        order_date,
        revenue_usd
    from {{ ref('int_ga4__orders') }}

),

sessions as (

    select
        session_key,
        user_pseudo_id,
        session_start_ts_utc,
        session_channel_group
    from {{ ref('int_ga4__sessions') }}

),

touchpoints as (

    select
        orders.order_key,
        orders.order_date,
        orders.revenue_usd,
        sessions.session_key,
        sessions.session_start_ts_utc,
        coalesce(sessions.session_channel_group, 'Unassigned') as channel_group
    from orders
    left join sessions
        on
            orders.user_pseudo_id = sessions.user_pseudo_id
            and orders.order_ts_utc >= sessions.session_start_ts_utc
            and {{ dbt.dateadd(
                'day', -var('attribution_lookback_days'), 'orders.order_ts_utc'
            ) }} <= sessions.session_start_ts_utc

),

positioned as (

    select
        order_key,
        order_date,
        revenue_usd,
        session_key,
        session_start_ts_utc,
        channel_group,
        channel_group = 'Direct' as is_direct,
        row_number() over (
            partition by order_key
            order by session_start_ts_utc, session_key
        ) as touch_position,
        count(*) over (partition by order_key) as touch_count,
        max(case when channel_group != 'Direct' then 1 else 0 end) over (
            partition by order_key
        ) as has_non_direct_touch,
        row_number() over (
            partition by order_key, channel_group = 'Direct'
            order by session_start_ts_utc desc, session_key desc
        ) as recency_within_direct_flag
    from touchpoints

),

final as (

    select
        order_key,
        order_date,
        revenue_usd,
        session_key,
        session_start_ts_utc,
        channel_group,
        touch_position,
        touch_count,
        case when touch_position = 1 then 1.0 else 0.0 end as first_touch_credit,
        case
            when has_non_direct_touch = 1
                then
                    case
                        when not is_direct and recency_within_direct_flag = 1 then 1.0
                        else 0.0
                    end
            when touch_position = touch_count then 1.0
            else 0.0
        end as last_non_direct_credit,
        1.0 / touch_count as linear_credit
    from positioned

)

select * from final
