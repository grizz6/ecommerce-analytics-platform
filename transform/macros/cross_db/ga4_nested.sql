{#
    Cross-database helpers for the GA4 export's nested fields.

    Snowflake stores nested GA4 fields as VARIANT and reads them with the
    colon path syntax. DuckDB reads the Parquet files as STRUCT and LIST and
    uses dot access. Every model calls these macros instead of either syntax,
    so the same model compiles on both targets.

    Logical types accepted by the macros: string, bigint, double, boolean.
#}

{% macro ga4_type(logical_type) %}
    {{ return(adapter.dispatch('ga4_type', 'ecommerce_analytics')(logical_type)) }}
{% endmacro %}

{% macro snowflake__ga4_type(logical_type) %}
    {%- set types = {'string': 'varchar', 'bigint': 'number(38, 0)', 'double': 'float', 'boolean': 'boolean'} -%}
    {{- types[logical_type] -}}
{% endmacro %}

{% macro duckdb__ga4_type(logical_type) %}
    {%- set types = {'string': 'varchar', 'bigint': 'bigint', 'double': 'double', 'boolean': 'boolean'} -%}
    {{- types[logical_type] -}}
{% endmacro %}


{#- Read a field from a nested record, for example device.web_info.browser. -#}
{% macro nested_field(column, path, logical_type='string') %}
    {{ return(adapter.dispatch('nested_field', 'ecommerce_analytics')(column, path, logical_type)) }}
{% endmacro %}

{% macro snowflake__nested_field(column, path, logical_type) -%}
    {{ column }}:{{ path }}::{{ ga4_type(logical_type) }}
{%- endmacro %}

{% macro duckdb__nested_field(column, path, logical_type) -%}
    cast({{ column }}.{{ path }} as {{ ga4_type(logical_type) }})
{%- endmacro %}


{#-
    Read one event parameter by key from the event_params array.
    value_type is the GA4 value slot: string_value, int_value, float_value or
    double_value. Returns null when the key is absent.
-#}
{% macro event_param(key, value_type='string_value', column='event_params') %}
    {{ return(adapter.dispatch('event_param', 'ecommerce_analytics')(key, value_type, column)) }}
{% endmacro %}

{% macro _event_param_logical_type(value_type) -%}
    {%- set types = {'string_value': 'string', 'int_value': 'bigint', 'float_value': 'double', 'double_value': 'double'} -%}
    {%- if value_type not in types -%}
        {{ exceptions.raise_compiler_error("event_param: unknown value_type '" ~ value_type ~ "'") }}
    {%- endif -%}
    {{- types[value_type] -}}
{%- endmacro %}

{% macro snowflake__event_param(key, value_type, column) -%}
    filter({{ column }}::array, p -> p:key::varchar = '{{ key }}')[0]:value:{{ value_type }}::{{ ga4_type(_event_param_logical_type(value_type)) }}
{%- endmacro %}

{% macro duckdb__event_param(key, value_type, column) -%}
    cast(list_filter({{ column }}, p -> p.key = '{{ key }}')[1].value.{{ value_type }} as {{ ga4_type(_event_param_logical_type(value_type)) }})
{%- endmacro %}


{#-
    Read an event parameter as text whichever value slot holds it. GA4 stores
    some parameters, such as session_engaged, as a string on some events and
    a number on others.
-#}
{% macro event_param_as_string(key, column='event_params') -%}
    coalesce(
        {{ event_param(key, 'string_value', column) }},
        cast({{ event_param(key, 'int_value', column) }} as {{ ga4_type('string') }}),
        cast({{ event_param(key, 'double_value', column) }} as {{ ga4_type('string') }})
    )
{%- endmacro %}


{#-
    Flatten an array into one row per element, for use after a comma in a
    FROM clause. Read elements with flattened_value() and their zero-based
    position with flattened_index(). Rows with empty arrays are dropped on
    both targets.
-#}
{% macro flatten_array(column, alias) %}
    {{ return(adapter.dispatch('flatten_array', 'ecommerce_analytics')(column, alias)) }}
{% endmacro %}

{% macro snowflake__flatten_array(column, alias) -%}
    lateral flatten(input => {{ column }}) as {{ alias }}
{%- endmacro %}

{% macro duckdb__flatten_array(column, alias) -%}
    unnest({{ column }}) with ordinality as {{ alias }}(value, position)
{%- endmacro %}

{% macro flattened_value(alias) -%}
    {{ alias }}.value
{%- endmacro %}

{% macro flattened_index(alias) %}
    {{ return(adapter.dispatch('flattened_index', 'ecommerce_analytics')(alias)) }}
{% endmacro %}

{% macro snowflake__flattened_index(alias) -%}
    {{ alias }}.index
{%- endmacro %}

{% macro duckdb__flattened_index(alias) -%}
    ({{ alias }}.position - 1)
{%- endmacro %}


{#- Number of elements in an array, or 0 when it is null. -#}
{% macro array_length(column) %}
    {{ return(adapter.dispatch('array_length', 'ecommerce_analytics')(column)) }}
{% endmacro %}

{% macro snowflake__array_length(column) -%}
    coalesce(array_size({{ column }}), 0)
{%- endmacro %}

{% macro duckdb__array_length(column) -%}
    coalesce(len({{ column }}), 0)
{%- endmacro %}


{#- Stable text form of a nested value, used to fingerprint event parameters. -#}
{% macro nested_as_json(column) %}
    {{ return(adapter.dispatch('nested_as_json', 'ecommerce_analytics')(column)) }}
{% endmacro %}

{% macro snowflake__nested_as_json(column) -%}
    to_json({{ column }})
{%- endmacro %}

{% macro duckdb__nested_as_json(column) -%}
    cast(to_json({{ column }}) as varchar)
{%- endmacro %}
