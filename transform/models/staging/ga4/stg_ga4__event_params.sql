{#
    Every event parameter in long format: one row per event and parameter.
    Useful for exploring parameters that stg_ga4__events does not promote to
    columns.
#}

with

events as (

    select
        event_key,
        event_name,
        event_date,
        event_params
    from {{ ref('stg_ga4__events') }}

),

flattened as (

    select
        events.event_key,
        events.event_name,
        events.event_date,
        {{ nested_field(flattened_value('param'), 'key') }} as param_key,
        {{ nested_field(flattened_value('param'), 'value.string_value') }} as string_value,
        {{ nested_field(flattened_value('param'), 'value.int_value', 'bigint') }} as int_value,
        {{ nested_field(flattened_value('param'), 'value.float_value', 'double') }} as float_value,
        {{ nested_field(flattened_value('param'), 'value.double_value', 'double') }}
            as double_value
    from events,
        {{ flatten_array('events.event_params', 'param') }}

),

final as (

    select
        {{ dbt_utils.generate_surrogate_key(['event_key', 'param_key']) }} as event_param_key,
        event_key,
        event_name,
        event_date,
        param_key,
        string_value,
        int_value,
        float_value,
        double_value,
        -- The value as text, whichever slot GA4 used for it.
        coalesce(
            string_value,
            cast(int_value as {{ ga4_type('string') }}),
            cast(double_value as {{ ga4_type('string') }}),
            cast(float_value as {{ ga4_type('string') }})
        ) as param_value
    from flattened

)

select * from final
