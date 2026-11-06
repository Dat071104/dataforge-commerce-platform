
from dataforge.profile import profile
from dataforge.settings import SQL


def test_external_schema_profile(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("id,amount\n1,500\n2,300\n", encoding="utf-8")
    report = profile(tmp_path, tmp_path / "report.json")
    assert report["x.csv"]["columns"] == ["id", "amount"]
    assert len(report["x.csv"]["sample_rows"]) == 2


def test_all_sql_analytics_available_and_no_naive_payment_item_join():
    qs = list((SQL / "analysis").glob("q*.sql"))
    assert len(qs) == 10
    sql = (SQL / "build" / "010_marts.sql").read_text().lower()
    for t in ["dim_customer", "fct_order_item", "fct_payment", "fct_return",
              "fct_shipment", "vw_order_reconciliation", "valid_from", "valid_to"]:
        assert t in sql
    assert "with items as" in sql
