{# Use "staging"/"marts" as-is instead of dbt's default "<target>_staging". #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name | trim if custom_schema_name else target.schema }}
{%- endmacro %}
