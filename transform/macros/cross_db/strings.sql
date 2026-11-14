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


{#- SHA-256 of a value as lower-case hex. Used to publish user keys, not raw ids. -#}
{% macro hash_identifier(column) %}
    {{ return(adapter.dispatch('hash_identifier', 'ecommerce_analytics')(column)) }}
{% endmacro %}

{% macro snowflake__hash_identifier(column) -%}
    sha2(cast({{ column }} as varchar), 256)
{%- endmacro %}

{% macro duckdb__hash_identifier(column) -%}
    sha256(cast({{ column }} as varchar))
{%- endmacro %}
