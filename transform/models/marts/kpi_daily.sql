{#
    Headline KPIs per complete reporting day. Sessions, users and new users
    are counted by session date; orders and revenue by order date. Every
    complete day has a row, with zeros where nothing happened.
#}

with

days as (

    select date_day
    from {{ ref('dim_date') }}
    where is_complete_reporting_day

),

sessions as (

    select
        session_key,
        user_pseudo_id,
        session_date,
        is_first_session
    from {{ ref('int_ga4__sessions') }}

),

funnel as (

    select
        session_key,
        has_purchase
    from {{ ref('int_ga4__session_funnel') }}

),

session_stats as (

    select
        sessions.session_date,
        count(*) as sessions,
        count(distinct sessions.user_pseudo_id) as users,
        count(distinct case when sessions.is_first_session then sessions.user_pseudo_id end)
            as new_users,
        sum(case when funnel.has_purchase then 1 else 0 end) as purchasing_sessions
    from sessions
    inner join funnel
        on sessions.session_key = funnel.session_key
    group by sessions.session_date

),

order_stats as (

    select
        order_date,
        count(*) as orders,
        sum(revenue_usd) as revenue_usd
    from {{ ref('int_ga4__orders') }}
    group by order_date

),

combined as (

    select
        days.date_day,
        coalesce(session_stats.sessions, 0) as sessions,
        coalesce(session_stats.users, 0) as users,
        coalesce(session_stats.new_users, 0) as new_users,
        coalesce(session_stats.purchasing_sessions, 0) as purchasing_sessions,
        coalesce(order_stats.orders, 0) as orders,
        coalesce(order_stats.revenue_usd, 0) as revenue_usd
    from days
    left join session_stats
        on days.date_day = session_stats.session_date
    left join order_stats
        on days.date_day = order_stats.order_date

),

final as (

    select
        cast(date_day as date) as date_day,
        cast(sessions as bigint) as sessions,
        cast(users as bigint) as users,
        cast(new_users as bigint) as new_users,
        cast(purchasing_sessions as bigint) as purchasing_sessions,
        cast(orders as bigint) as purchases,
        cast(revenue_usd as double) as revenue_usd,
        cast({{ safe_divide('purchasing_sessions', 'sessions') }} as double) as conversion_rate,
        cast({{ safe_divide('revenue_usd', 'orders') }} as double) as average_order_value_usd,
        cast({{ safe_divide('revenue_usd', 'users') }} as double) as revenue_per_user_usd
    from combined

)

select * from final
