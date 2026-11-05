{#
    Schema naming that separates development from production.

    prod target:   a model configured with schema "marts" builds in MARTS.
    other targets: the same model builds in <target schema>_MARTS, for
                   example DEV_MARTS, so development never touches production.
    Models with no custom schema build in the target schema.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set default_schema = target.schema -%}
    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    {%- elif target.name == 'prod' -%}
        {{ custom_schema_name | trim }}
    {%- else -%}
        {{ default_schema }}_{{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
