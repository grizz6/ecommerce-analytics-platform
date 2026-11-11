{#
    Cross-database string helpers.
#}

{#- Case-insensitive match of the whole value against a regular expression. -#}
{% macro regex_full_match(column, pattern) %}
    {{ return(adapter.dispatch('regex_full_match', 'ecommerce_analytics')(column, pattern)) }}
{% endmacro %}

{% macro snowflake__regex_full_match(column, pattern) -%}
    regexp_like(lower({{ column }}), '{{ pattern }}')
{%- endmacro %}

{% macro duckdb__regex_full_match(column, pattern) -%}
    regexp_full_match(lower({{ column }}), '{{ pattern }}')
{%- endmacro %}
