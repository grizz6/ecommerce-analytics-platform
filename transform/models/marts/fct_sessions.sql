{#
    One row per session, with order counts and revenue. Users appear only as
    a hashed user_key.
#}

with

sessions as (

    select
        session_key,
        user_pseudo_id,
        is_first_session,
        session_date,
        session_start_ts_utc,
        session_end_ts_utc,
        event_count,
        page_views,
        is_engaged,
        engagement_time_msec,
        landing_page,
        device_category,
        device_operating_system,
        device_browser,
        geo_country,
        session_source,
        session_medium,
        session_campaign,
        session_channel_group
    from {{ ref('int_ga4__sessions') }}

),

funnel as (

    select
        session_key,
        has_purchase
    from {{ ref('int_ga4__session_funnel') }}

),

session_orders as (

    select
        session_key,
        count(*) as orders,
        sum(revenue_usd) as revenue_usd
    from {{ ref('int_ga4__orders') }}
    group by session_key

),

final as (

    select
        cast(sessions.session_key as varchar) as session_key,
        cast({{ hash_identifier('sessions.user_pseudo_id') }} as varchar) as user_key,
        cast(sessions.session_date as date) as session_date,
        cast(sessions.session_start_ts_utc as timestamp) as session_start_ts_utc,
        cast(sessions.session_end_ts_utc as timestamp) as session_end_ts_utc,
        cast(
            {{ dbt.datediff(
                'sessions.session_start_ts_utc', 'sessions.session_end_ts_utc', 'second'
            ) }} as bigint
        ) as session_duration_seconds,
        cast(sessions.is_first_session as boolean) as is_first_session,
        cast(sessions.is_engaged as boolean) as is_engaged,
        cast(sessions.event_count as bigint) as event_count,
        cast(sessions.page_views as bigint) as page_views,
        cast(sessions.engagement_time_msec as bigint) as engagement_time_msec,
        cast(sessions.landing_page as varchar) as landing_page,
        cast(sessions.device_category as varchar) as device_category,
        cast(sessions.device_operating_system as varchar) as device_operating_system,
        cast(sessions.device_browser as varchar) as device_browser,
        cast(sessions.geo_country as varchar) as geo_country,
        cast(sessions.session_source as varchar) as session_source,
        cast(sessions.session_medium as varchar) as session_medium,
        cast(sessions.session_campaign as varchar) as session_campaign,
        cast(sessions.session_channel_group as varchar) as session_channel_group,
        cast(coalesce(funnel.has_purchase, false) as boolean) as has_purchase,
        cast(coalesce(session_orders.orders, 0) as bigint) as orders,
        cast(coalesce(session_orders.revenue_usd, 0) as double) as revenue_usd
    from sessions
    left join funnel
        on sessions.session_key = funnel.session_key
    left join session_orders
        on sessions.session_key = session_orders.session_key

)

select * from final
