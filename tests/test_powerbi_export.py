from datetime import date
from decimal import Decimal

from scripts import export_powerbi_gold


def test_powerbi_export_is_whitelisted_to_gold_tables() -> None:
    names = [(schema, table) for schema, table, _ in export_powerbi_gold.TABLES]
    assert len(names) == 11
    assert len(set(names)) == len(names)
    assert all(schema in {"dw", "analytics"} for schema, _ in names)
    assert ("analytics", "vw_order_reconciliation") in names


def test_excel_snapshot_preserves_supported_scalar_types() -> None:
    assert export_powerbi_gold._excel_value(Decimal("123456.00")) == 123456.0
    assert export_powerbi_gold._excel_value(date(2022, 1, 1)) == date(2022, 1, 1)
    assert export_powerbi_gold._excel_value("synthetic") == "synthetic"
