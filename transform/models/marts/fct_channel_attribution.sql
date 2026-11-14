{#
    Attributed orders and revenue per order date, channel and attribution
    model (first_touch, last_non_direct, linear), on complete reporting days.
    Uses a var('attribution_lookback_days') lookback; orders early in the data
    have a shorter effective lookback because sessions before 2020-11-01 are
    not in the dataset.
#}

with

touchpoints as (

    select
        order_date,
        channel_group,
        revenue_usd,
        first_touch_credit,
        last_non_direct_credit,
        linear_credit
    from {{ ref('int_ga4__order_touchpoints') }}

),

complete_days as (

    select date_day
    from {{ ref('dim_date') }}
    where is_complete_reporting_day

),

credits as (

    select
        order_date,
        channel_group,
        'first_touch' as attribution_model,
        first_touch_credit as credit,
        revenue_usd
    from touchpoints

    union all

    select
        order_date,
        channel_group,
        'last_non_direct' as attribution_model,
        last_non_direct_credit as credit,
        revenue_usd
    from touchpoints

    union all

    select
        order_date,
        channel_group,
        'linear' as attribution_model,
        linear_credit as credit,
        revenue_usd
    from touchpoints

),

aggregated as (

    select
        credits.order_date,
        credits.channel_group,
        credits.attribution_model,
        sum(credits.credit) as attributed_orders,
        sum(credits.credit * credits.revenue_usd) as attributed_revenue_usd
    from credits
    inner join complete_days
        on credits.order_date = complete_days.date_day
    group by credits.order_date, credits.channel_group, credits.attribution_model

),

final as (

    select
        cast(order_date as date) as order_date,
        cast(channel_group as varchar) as channel_group,
        cast(attribution_model as varchar) as attribution_model,
        cast(attributed_orders as double) as attributed_orders,
        cast(attributed_revenue_usd as double) as attributed_revenue_usd
    from aggregated

)

select * from final
