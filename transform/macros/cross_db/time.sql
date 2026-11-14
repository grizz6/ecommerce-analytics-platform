{#
    Cross-database time helpers. GA4 timestamps are microseconds since the
    Unix epoch, in UTC. Both targets produce a timestamp without time zone
    that represents UTC, and convert it to the reporting time zone when
    asked.
#}

{% macro micros_to_timestamp(column) %}
    {{ return(adapter.dispatch('micros_to_timestamp', 'ecommerce_analytics')(column)) }}
{% endmacro %}

{% macro snowflake__micros_to_timestamp(column) -%}
    to_timestamp_ntz({{ column }}, 6)
{%- endmacro %}

{% macro duckdb__micros_to_timestamp(column) -%}
    make_timestamp({{ column }})
{%- endmacro %}


{#- Convert a UTC timestamp to local time in var('reporting_timezone'). -#}
{% macro to_reporting_time(utc_timestamp) %}
    {{ return(adapter.dispatch('to_reporting_time', 'ecommerce_analytics')(utc_timestamp)) }}
{% endmacro %}

{% macro snowflake__to_reporting_time(utc_timestamp) -%}
    convert_timezone('UTC', '{{ var("reporting_timezone") }}', {{ utc_timestamp }})
{%- endmacro %}

{% macro duckdb__to_reporting_time(utc_timestamp) -%}
    timezone('{{ var("reporting_timezone") }}', {{ utc_timestamp }} at time zone 'UTC')
{%- endmacro %}


{#- Parse GA4's YYYYMMDD event_date text into a date. -#}
{% macro parse_yyyymmdd(column) %}
    {{ return(adapter.dispatch('parse_yyyymmdd', 'ecommerce_analytics')(column)) }}
{% endmacro %}

{% macro snowflake__parse_yyyymmdd(column) -%}
    to_date({{ column }}, 'YYYYMMDD')
{%- endmacro %}

{% macro duckdb__parse_yyyymmdd(column) -%}
    cast(strptime({{ column }}, '%Y%m%d') as date)
{%- endmacro %}

{#- ISO day of week: Monday is 1, Sunday is 7. -#}
{% macro iso_day_of_week(column) %}
    {{ return(adapter.dispatch('iso_day_of_week', 'ecommerce_analytics')(column)) }}
{% endmacro %}

{% macro snowflake__iso_day_of_week(column) -%}
    dayofweekiso({{ column }})
{%- endmacro %}

{% macro duckdb__iso_day_of_week(column) -%}
    isodow({{ column }})
{%- endmacro %}


{#- Monday of the ISO week containing a date, as a date. -#}
{% macro iso_week_start(column) -%}
    cast({{ dbt.date_trunc('week', column) }} as date)
{%- endmacro %}
