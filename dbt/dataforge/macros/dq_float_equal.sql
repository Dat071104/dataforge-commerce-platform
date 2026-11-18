{% macro dq_float_equal(
    left_expression,
    right_expression,
    tolerance=0.000001
) -%}
    ABS(
        CAST({{ left_expression }} AS FLOAT64)
        - CAST({{ right_expression }} AS FLOAT64)
    ) <= {{ tolerance }}
{%- endmacro %}
