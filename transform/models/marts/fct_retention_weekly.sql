{#
    Weekly retention by first-visit cohort, acquisition channel and first
    device, over complete ISO weeks (Monday to Sunday).

    A cohort is the users whose first ever session (ga_session_number = 1)
    falls in that week. Users first seen on a later session were acquired
    before the data starts and are left out. A user is active in a week if
    they had any session in it. Every cohort has a row for every complete
    week from its first week onward, with zero activity where nobody
    returned, so week 0 retention is always 1.
#}

with

complete_weeks as (

    select distinct week_start_date
    from {{ ref('dim_date') }}
    where is_complete_week

),

sessions as (

    select
        user_pseudo_id,
        session_key,
        session_start_ts_utc,
        is_first_session,
        session_channel_group,
        device_category,
        {{ iso_week_start('session_date') }} as activity_week_start_date
    from {{ ref('int_ga4__sessions') }}

),

sessions_in_complete_weeks as (

    select sessions.*
    from sessions
    inner join complete_weeks
        on sessions.activity_week_start_date = complete_weeks.week_start_date

),

first_sessions as (

    select
        user_pseudo_id,
        is_first_session,
        activity_week_start_date as cohort_week_start_date,
        session_channel_group as first_touch_channel_group,
        coalesce(device_category, '(not set)') as first_device_category
    from sessions_in_complete_weeks
    qualify
        row_number() over (
            partition by user_pseudo_id
            order by session_start_ts_utc, session_key
        ) = 1

),

cohort_users as (

    select
        user_pseudo_id,
        cohort_week_start_date,
        first_touch_channel_group,
        first_device_category
    from first_sessions
    where is_first_session

),

cohort_sizes as (

    select
        cohort_week_start_date,
        first_touch_channel_group,
        first_device_category,
        count(*) as cohort_users
    from cohort_users
    group by cohort_week_start_date, first_touch_channel_group, first_device_category

),

weekly_activity as (

    select
        cohort_users.cohort_week_start_date,
        cohort_users.first_touch_channel_group,
        cohort_users.first_device_category,
        sessions_in_complete_weeks.activity_week_start_date,
        count(distinct cohort_users.user_pseudo_id) as active_users
    from cohort_users
    inner join sessions_in_complete_weeks
        on cohort_users.user_pseudo_id = sessions_in_complete_weeks.user_pseudo_id
    group by
        cohort_users.cohort_week_start_date,
        cohort_users.first_touch_channel_group,
        cohort_users.first_device_category,
        sessions_in_complete_weeks.activity_week_start_date

),

grid as (

    select
        cohort_sizes.cohort_week_start_date,
        cohort_sizes.first_touch_channel_group,
        cohort_sizes.first_device_category,
        cohort_sizes.cohort_users,
        complete_weeks.week_start_date as activity_week_start_date
    from cohort_sizes
    inner join complete_weeks
        on cohort_sizes.cohort_week_start_date <= complete_weeks.week_start_date

),

final as (

    select
        cast(grid.cohort_week_start_date as date) as cohort_week_start_date,
        cast(grid.activity_week_start_date as date) as activity_week_start_date,
        cast(
            {{ dbt.datediff(
                'grid.cohort_week_start_date', 'grid.activity_week_start_date', 'day'
            ) }} / 7 as bigint
        ) as weeks_since_first_visit,
        cast(grid.first_touch_channel_group as varchar) as first_touch_channel_group,
        cast(grid.first_device_category as varchar) as first_device_category,
        cast(grid.cohort_users as bigint) as cohort_users,
        cast(coalesce(weekly_activity.active_users, 0) as bigint) as active_users,
        cast(
            {{ safe_divide('coalesce(weekly_activity.active_users, 0)', 'grid.cohort_users') }}
            as double
        ) as retention_rate
    from grid
    left join weekly_activity
        on
            grid.cohort_week_start_date = weekly_activity.cohort_week_start_date
            and grid.first_touch_channel_group = weekly_activity.first_touch_channel_group
            and grid.first_device_category = weekly_activity.first_device_category
            and grid.activity_week_start_date = weekly_activity.activity_week_start_date

)

select * from final
