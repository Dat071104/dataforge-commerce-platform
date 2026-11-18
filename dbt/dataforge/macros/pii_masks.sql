{% macro pii_mask_email(email_expression) -%}
case
    when {{ email_expression }} is null then null
    when regexp_contains(cast({{ email_expression }} as string), r'^[A-Za-z0-9._+-]+@example\.com$')
        then concat(substr(cast({{ email_expression }} as string), 1, 1), '***@example.com')
    else null
end
{%- endmacro %}
