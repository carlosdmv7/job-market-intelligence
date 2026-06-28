{# Use the custom +schema verbatim (raw/staging/marts) instead of
   <target_schema>_<custom>, so relations land in exactly raw/staging/marts. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
