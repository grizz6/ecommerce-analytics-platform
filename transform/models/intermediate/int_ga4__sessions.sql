{#
    One row per session. A session is user_pseudo_id plus ga_session_id;
    events without a ga_session_id cannot be placed in a session and are left
    out (they remain in stg_ga4__events).

    Session attributes come from the session's events:
    - device and location: the first event of the session
    - landing page: the first page_view
    - source, medium and campaign: the first event in the session that
      carries traffic parameters; sessions with none are (direct) / (none),
      as GA4 reports them
    - channel group: GA4 default channel group rules on that source and medium
#}

with

events as (

    select
        session_key,
        event_key,
        user_pseudo_id,
        ga_session_id,
        ga_session_number,
        event_name,
        event_ts_utc,
        event_ts_local,
        reporting_date,
        page_location,
        is_session_engaged,
        engagement_time_msec,
        event_source,
        event_medium,
        event_campaign,
        device_category,
        device_operating_system,
        device_browser,
        geo_country,
        geo_region,
        geo_city
    from {{ ref('stg_ga4__events') }}
    where session_key is not null

),

source_categories as (

    select
        source_category,
        lower(source) as category_source
    from {{ ref('ga4_source_categories') }}

),

session_totals as (

    select
        session_key,
        min(user_pseudo_id) as user_pseudo_id,
        min(ga_session_id) as ga_session_id,
        max(ga_session_number) as ga_session_number,
        min(event_ts_utc) as session_start_ts_utc,
        max(event_ts_utc) as session_end_ts_utc,
        min(event_ts_local) as session_start_ts_local,
        count(*) as event_count,
        sum(case when event_name = 'page_view' then 1 else 0 end) as page_views,
        max(case when is_session_engaged then 1 else 0 end) = 1 as is_engaged,
        coalesce(sum(engagement_time_msec), 0) as engagement_time_msec
    from events
    group by session_key

),

first_event as (

    select
        session_key,
        reporting_date as session_date,
        device_category,
        device_operating_system,
        device_browser,
        geo_country,
        geo_region,
        geo_city
    from events
    qualify
        row_number() over (partition by session_key order by event_ts_utc, event_key) = 1

),

landing_page as (

    select
        session_key,
        page_location as landing_page
    from events
    where event_name = 'page_view'
    qualify
        row_number() over (partition by session_key order by event_ts_utc, event_key) = 1

),

session_traffic as (

    select
        session_key,
        event_source as session_source,
        event_medium as session_medium,
        event_campaign as session_campaign
    from events
    where event_source is not null or event_medium is not null
    qualify
        row_number() over (partition by session_key order by event_ts_utc, event_key) = 1

),

joined as (

    select
        session_totals.session_key,
        session_totals.user_pseudo_id,
        session_totals.ga_session_id,
        session_totals.ga_session_number,
        first_event.session_date,
        session_totals.session_start_ts_utc,
        session_totals.session_end_ts_utc,
        session_totals.session_start_ts_local,
        session_totals.event_count,
        session_totals.page_views,
        session_totals.is_engaged,
        session_totals.engagement_time_msec,
        landing_page.landing_page,
        first_event.device_category,
        first_event.device_operating_system,
        first_event.device_browser,
        first_event.geo_country,
        first_event.geo_region,
        first_event.geo_city,
        coalesce(session_totals.ga_session_number = 1, false) as is_first_session,
        coalesce(session_traffic.session_source, '(direct)') as session_source,
        coalesce(session_traffic.session_medium, '(none)') as session_medium,
        coalesce(session_traffic.session_campaign, '(direct)') as session_campaign
    from session_totals
    inner join first_event
        on session_totals.session_key = first_event.session_key
    left join landing_page
        on session_totals.session_key = landing_page.session_key
    left join session_traffic
        on session_totals.session_key = session_traffic.session_key

),

final as (

    select
        joined.session_key,
        joined.user_pseudo_id,
        joined.ga_session_id,
        joined.ga_session_number,
        joined.is_first_session,
        joined.session_date,
        joined.session_start_ts_utc,
        joined.session_end_ts_utc,
        joined.session_start_ts_local,
        joined.event_count,
        joined.page_views,
        joined.is_engaged,
        joined.engagement_time_msec,
        joined.landing_page,
        joined.device_category,
        joined.device_operating_system,
        joined.device_browser,
        joined.geo_country,
        joined.geo_region,
        joined.geo_city,
        joined.session_source,
        joined.session_medium,
        joined.session_campaign,
        {{ default_channel_group(
            'joined.session_source',
            'joined.session_medium',
            'joined.session_campaign',
            'source_categories.source_category'
        ) }} as session_channel_group
    from joined
    left join source_categories
        on lower(joined.session_source) = source_categories.category_source

)

select * from final
