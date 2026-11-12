from __future__ import annotations

import pytest

from scripts.week7_compare_full_incremental import (
    EXPECTED_PROJECT,
    Week7ComparisonError,
    build_comparison_sql,
)


def test_comparison_uses_only_isolated_week7_candidate_datasets():
    sql = build_comparison_sql(EXPECTED_PROJECT)
    assert f"{EXPECTED_PROJECT}.dbt_week7.fct_week7_order_reconciliation" in sql
    assert f"{EXPECTED_PROJECT}.dbt_week7_full.fct_week7_order_reconciliation" in sql
    assert "FULL OUTER JOIN" in sql
    assert "mismatch_rows" in sql
    assert "collected_amount" in sql


def test_comparison_rejects_a_different_project():
    with pytest.raises(Week7ComparisonError, match="approved project"):
        build_comparison_sql("unrelated-project")
