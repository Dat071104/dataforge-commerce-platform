from dataforge.settings import ROOT
from scripts.benchmark_warehouse import _plan_nodes, _q10_select


def test_benchmark_query_is_extracted_from_q10_sql():
    query = _q10_select()
    assert query.startswith("SELECT f.product_key")
    assert "f.order_date_key BETWEEN 20220101 AND 20220131" in query
    assert "fulfilled_sales_proxy" in query


def test_candidate_index_covers_q10_filter_group_and_measure():
    index_sql = (ROOT / "sql" / "performance" / "002_q10_covering_index.sql")
    source = index_sql.read_text(encoding="utf-8").lower()
    assert "on dw.fct_order_item(order_date_key, product_key)" in source
    assert "include (fulfilled_sales_proxy)" in source


def test_plan_summary_visits_scan_and_aggregate_nodes():
    plan = {
        "Node Type": "Limit",
        "Actual Rows": 10,
        "Plans": [
            {"Node Type": "Aggregate", "Actual Rows": 10,
             "Plans": [{"Node Type": "Seq Scan", "Actual Rows": 42}]},
        ],
    }
    nodes = _plan_nodes(plan)
    assert [node["node_type"] for node in nodes] == ["Limit", "Aggregate", "Seq Scan"]
    assert nodes[-1]["actual_rows"] == 42
