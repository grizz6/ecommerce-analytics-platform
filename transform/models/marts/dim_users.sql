{#
    One row per user, keyed by a SHA-256 hash of user_pseudo_id. First-seen
    attributes come from the user's first observed session. is_new_user is
    true when that session is the user's first ever (ga_session_number = 1);
    users first observed on a later session were acquired before the data
    starts and are excluded from retention cohorts.
#}

with

sessions as (

    select
        user_pseudo_id,
        session_key,
        session_start_ts_utc,
        session_date,
        is_first_session,
        session_channel_group,
        device_category,
        geo_country
    from {{ ref('int_ga4__sessions') }}

),

first_sessions as (

    select
        user_pseudo_id,
        session_date as first_seen_date,
        is_first_session as is_new_user,
        session_channel_group as first_touch_channel_group,
        device_category as first_device_category,
        geo_country as first_country
    from sessions
    qualify
        row_number() over (
            partition by user_pseudo_id
            order by session_start_ts_utc, session_key
        ) = 1

),

session_counts as (

    select
        user_pseudo_id,
        count(*) as sessions
    from sessions
    group by user_pseudo_id

),

order_totals as (

    select
        user_pseudo_id,
        count(*) as orders,
        sum(revenue_usd) as revenue_usd
    from {{ ref('int_ga4__orders') }}
    group by user_pseudo_id

),

final as (

    select
        cast({{ hash_identifier('first_sessions.user_pseudo_id') }} as varchar) as user_key,
        cast(first_sessions.first_seen_date as date) as first_seen_date,
        cast({{ iso_week_start('first_sessions.first_seen_date') }} as date)
            as first_seen_week_start_date,
        cast(first_sessions.is_new_user as boolean) as is_new_user,
        cast(first_sessions.first_touch_channel_group as varchar) as first_touch_channel_group,
        cast(first_sessions.first_device_category as varchar) as first_device_category,
        cast(first_sessions.first_country as varchar) as first_country,
        cast(session_counts.sessions as bigint) as sessions,
        cast(coalesce(order_totals.orders, 0) as bigint) as orders,
        cast(coalesce(order_totals.revenue_usd, 0) as double) as revenue_usd,
        cast(coalesce(order_totals.orders, 0) > 0 as boolean) as is_purchaser
    from first_sessions
    inner join session_counts
        on first_sessions.user_pseudo_id = session_counts.user_pseudo_id
    left join order_totals
        on first_sessions.user_pseudo_id = order_totals.user_pseudo_id

)

select * from final
