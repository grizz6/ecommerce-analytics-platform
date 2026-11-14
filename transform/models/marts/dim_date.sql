{#
    One row per calendar date covered by the data in the reporting time zone,
    2020-10-31 to 2021-01-31. Marks complete reporting days and complete ISO
    weeks (Monday to Sunday), which daily and weekly marts use to leave out
    the partial first and last days.
#}

with

spine as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('2020-10-31' as date)",
        end_date="cast('2021-02-01' as date)"
    ) }}

),

days as (

    select
        cast(date_day as date) as date_day,
        cast(date_day as date) between cast('{{ var("first_complete_reporting_date") }}' as date)
        and cast('{{ var("last_complete_reporting_date") }}' as date) as is_complete_reporting_day
    from spine

),

with_calendar as (

    select
        date_day,
        is_complete_reporting_day,
        {{ iso_week_start('date_day') }} as week_start_date,
        cast({{ dbt.date_trunc('month', 'date_day') }} as date) as month_start_date,
        {{ iso_day_of_week('date_day') }} as iso_day_of_week,
        extract(year from date_day) as calendar_year,
        extract(month from date_day) as calendar_month
    from days

),

week_completeness as (

    select
        week_start_date,
        sum(case when is_complete_reporting_day then 1 else 0 end) as complete_days_in_week
    from with_calendar
    group by week_start_date

),

final as (

    select
        cast(with_calendar.date_day as date) as date_day,
        cast(with_calendar.week_start_date as date) as week_start_date,
        cast(with_calendar.month_start_date as date) as month_start_date,
        cast(with_calendar.calendar_year as bigint) as calendar_year,
        cast(with_calendar.calendar_month as bigint) as calendar_month,
        cast(with_calendar.iso_day_of_week as bigint) as iso_day_of_week,
        cast(
            case with_calendar.iso_day_of_week
                when 1 then 'Monday'
                when 2 then 'Tuesday'
                when 3 then 'Wednesday'
                when 4 then 'Thursday'
                when 5 then 'Friday'
                when 6 then 'Saturday'
                when 7 then 'Sunday'
            end as varchar
        ) as day_name,
        cast(with_calendar.iso_day_of_week in (6, 7) as boolean) as is_weekend,
        cast(with_calendar.is_complete_reporting_day as boolean) as is_complete_reporting_day,
        -- A week counts only if all seven of its days are complete.
        cast(week_completeness.complete_days_in_week = 7 as boolean) as is_complete_week
    from with_calendar
    inner join week_completeness
        on with_calendar.week_start_date = week_completeness.week_start_date

)

select * from final
