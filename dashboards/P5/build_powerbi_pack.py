"""Generate the local, synthetic-only DataForge PBIP/PBIR/TMDL source pack.

The source workbook is created separately by scripts/export_powerbi_gold.py.
This script writes only project files below dashboards/P5/DataForge.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[2]
P5 = Path(__file__).resolve().parent
PROJECT = P5 / "DataForge"
MODEL = PROJECT / "DataForge.SemanticModel"
MODEL_DEF = MODEL / "definition"
TABLES_DIR = MODEL_DEF / "tables"
ROLES_DIR = MODEL_DEF / "roles"
REPORT = PROJECT / "DataForge.Report"
REPORT_DEF = REPORT / "definition"
PAGES_DIR = REPORT_DEF / "pages"
GOLD_FILE = ROOT / "data" / "powerbi_gold_export" / "DataForgeGold.xlsx"

# TMDL table schema: column, model type, M type, format, summarizeBy, hidden, key.
TABLES = {
    "dim_date": [
        ("date_key", "int64", "Int64.Type", "0", "none", True, False),
        ("calendar_date", "dateTime", "type date", "yyyy-mm-dd", "none", False, True),
        ("year", "int64", "Int64.Type", "0", "none", False, False),
        ("month", "int64", "Int64.Type", "0", "none", False, False),
        ("month_start", "dateTime", "type date", "mmm yyyy", "none", False, False),
        ("quarter", "int64", "Int64.Type", "0", "none", False, False),
    ],
    "dim_customer": [
        ("customer_key", "int64", "Int64.Type", "0", "none", True, True),
        ("customer_id", "string", "type text", None, "none", False, False),
        ("segment", "string", "type text", None, "none", False, False),
        ("valid_from", "dateTime", "type date", "yyyy-mm-dd", "none", True, False),
        ("valid_to", "dateTime", "type date", "yyyy-mm-dd", "none", True, False),
        ("is_current", "boolean", "type logical", None, "none", True, False),
        ("signup_date", "dateTime", "type date", "yyyy-mm-dd", "none", True, False),
        ("geography_key", "int64", "Int64.Type", "0", "none", True, False),
        ("customer_region", "string", "type text", None, "none", False, False),
    ],
    "dim_product": [
        ("product_key", "int64", "Int64.Type", "0", "none", True, True),
        ("product_id", "string", "type text", None, "none", False, False),
        ("category", "string", "type text", None, "none", False, False),
        ("subcategory", "string", "type text", None, "none", False, False),
        ("base_price", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("unit_cogs", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
    ],
    "dim_geography": [
        ("geography_key", "int64", "Int64.Type", "0", "none", True, True),
        ("province_id", "string", "type text", None, "none", True, False),
        ("province", "string", "type text", None, "none", False, False),
        ("region", "string", "type text", None, "none", False, False),
    ],
    "fct_order_item": [
        ("order_item_id", "string", "type text", None, "none", True, True),
        ("order_id", "string", "type text", None, "none", False, False),
        ("order_date_key", "int64", "Int64.Type", "0", "none", True, False),
        ("customer_key", "int64", "Int64.Type", "0", "none", True, False),
        ("product_key", "int64", "Int64.Type", "0", "none", True, False),
        ("geography_key", "int64", "Int64.Type", "0", "none", True, False),
        ("order_status", "string", "type text", None, "none", False, False),
        ("quantity", "int64", "Int64.Type", "0", "sum", False, False),
        ("unit_price", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("discount_pct", "decimal", "Currency.Type", "0.00%", "average", False, False),
        ("gross_item_value", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("discount_value", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("net_order_value", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("fulfilled_sales_proxy", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("fulfilled_cogs_proxy", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
    ],
    "fct_payment": [
        ("payment_id", "string", "type text", None, "none", True, True),
        ("order_id", "string", "type text", None, "none", False, False),
        ("geography_key", "int64", "Int64.Type", "0", "none", True, False),
        ("payment_date_key", "int64", "Int64.Type", "0", "none", True, False),
        ("method", "string", "type text", None, "none", False, False),
        ("status", "string", "type text", None, "none", False, False),
        ("amount", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("collected_amount", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
    ],
    "fct_return": [
        ("return_id", "string", "type text", None, "none", True, True),
        ("order_id", "string", "type text", None, "none", False, False),
        ("order_item_id", "string", "type text", None, "none", True, False),
        ("geography_key", "int64", "Int64.Type", "0", "none", True, False),
        ("return_date_key", "int64", "Int64.Type", "0", "none", True, False),
        ("status", "string", "type text", None, "none", False, False),
        ("refund_amount", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("completed_refund", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
    ],
    "fct_shipment": [
        ("shipment_id", "string", "type text", None, "none", True, True),
        ("order_id", "string", "type text", None, "none", False, False),
        ("geography_key", "int64", "Int64.Type", "0", "none", True, False),
        ("ship_date_key", "int64", "Int64.Type", "0", "none", True, False),
        ("delivery_date_key", "int64", "Int64.Type", "0", "none", True, False),
        ("carrier", "string", "type text", None, "none", False, False),
        ("status", "string", "type text", None, "none", False, False),
        ("transit_days", "int64", "Int64.Type", "0", "average", False, False),
        ("late_over_3_days", "boolean", "type logical", None, "none", False, False),
    ],
    "fct_weather_daily": [
        ("date_key", "int64", "Int64.Type", "0", "none", True, False),
        ("geography_key", "int64", "Int64.Type", "0", "none", True, False),
        ("precipitation_mm", "decimal", "Currency.Type", "0.000", "average", False, False),
        ("temp_max_c", "decimal", "Currency.Type", "0.00", "average", False, False),
        ("source", "string", "type text", None, "none", False, False),
    ],
    "vw_order_reconciliation": [
        ("order_id", "string", "type text", None, "none", False, True),
        ("order_date_key", "int64", "Int64.Type", "0", "none", True, False),
        ("geography_key", "int64", "Int64.Type", "0", "none", True, False),
        ("ordered_net_value", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("expected_collection_proxy", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("collected", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("completed_refunds", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
        ("collection_variance", "decimal", "Currency.Type", "#,##0.00", "sum", False, False),
    ],
}

# Measure tuple: table, name, DAX, format, folder, description.
MEASURES = [
    ("fct_order_item", "Fulfilled Sales Proxy", "SUM('fct_order_item'[fulfilled_sales_proxy])", "#,##0.00", "Currency (VND)", "Delivered net item value; an analytics proxy, not recognized revenue."),
    ("fct_order_item", "Gross Ordered Value", "SUM('fct_order_item'[gross_item_value])", "#,##0.00", "Currency (VND)", "Gross item value across all order statuses."),
    ("fct_order_item", "Net Ordered Value", "SUM('fct_order_item'[net_order_value])", "#,##0.00", "Currency (VND)", "Net item value across all order statuses; not revenue."),
    ("fct_order_item", "Delivered Orders", "CALCULATE(DISTINCTCOUNT('fct_order_item'[order_id]), 'fct_order_item'[order_status] = \"delivered\")", "#,##0", "Orders", "Distinct delivered orders within item-fact filter context."),
    ("fct_order_item", "Delivered Item Lines", "CALCULATE(DISTINCTCOUNT('fct_order_item'[order_item_id]), 'fct_order_item'[order_status] = \"delivered\")", "#,##0", "Return Rate", "Distinct delivered item-line denominator."),
    ("fct_order_item", "Returned Delivered Item Lines (Eventual)", "VAR DeliveredItemIDs = CALCULATETABLE(VALUES('fct_order_item'[order_item_id]), 'fct_order_item'[order_status] = \"delivered\") RETURN CALCULATE(DISTINCTCOUNT('fct_return'[order_item_id]), REMOVEFILTERS('dim_date'), 'fct_return'[status] = \"completed\", TREATAS(DeliveredItemIDs, 'fct_return'[order_item_id]))", "#,##0", "Return Rate", "Completed return events eventually associated with selected delivered item IDs; ignores return-date filtering."),
    ("fct_order_item", "Return Line Rate", "DIVIDE([Returned Delivered Item Lines (Eventual)], [Delivered Item Lines])", "0.0%", "Return Rate", "Unique delivered item lines with at least one completed return divided by delivered item lines; not a unit-return rate."),
    ("fct_order_item", "Return Line Rate Date Rule", "\"Late/P90: delivery date; weather: observation date; completed returns by order date; no return-date filter.\"", None, "Report Notes", "Makes the report date-role rules visible."),
    ("fct_order_item", "Average Order Value", "DIVIDE([Fulfilled Sales Proxy], [Delivered Orders])", "#,##0", "Currency (VND)", "Unrounded fulfilled sales proxy per delivered order; model format is whole VND, Executive card overrides to millions with two decimals."),
    ("fct_order_item", "Fulfilled COGS Proxy", "SUM('fct_order_item'[fulfilled_cogs_proxy])", "#,##0.00", "Currency (VND)", "Product COGS proxy on delivered lines."),
    ("fct_order_item", "Gross Margin Proxy", "[Fulfilled Sales Proxy] - [Fulfilled COGS Proxy]", "#,##0.00", "Currency (VND)", "Sales proxy less COGS proxy; excludes tax, shipping and overhead."),
    ("fct_order_item", "Margin Proxy %", "DIVIDE([Gross Margin Proxy], [Fulfilled Sales Proxy])", "0.0%", "Percentages", "Gross margin proxy divided by fulfilled sales proxy."),
    ("fct_order_item", "Previous Month Sales", "CALCULATE([Fulfilled Sales Proxy], DATEADD('dim_date'[calendar_date], -1, MONTH))", "#,##0.00", "Currency (VND)", "Previous month fulfilled sales proxy by order date."),
    ("fct_order_item", "MoM Sales Growth %", "DIVIDE([Fulfilled Sales Proxy] - [Previous Month Sales], [Previous Month Sales])", "0.0%", "Percentages", "Month-over-month change in fulfilled sales proxy."),
    ("fct_order_item", "Demo Data Notice", "\"DEMO ONLY • Currency VND • sales proxy is not recognized revenue.\"", None, "Report Notes", "Visible source, currency, and metric caveat."),
    ("fct_order_item", "Inventory Scope Note", "\"Global inventory is excluded from this regional RLS model because it has no geography key.\"", None, "Report Notes", "Explains the deliberate omission of the inventory fact."),
    ("fct_payment", "Collected Payments", "SUM('fct_payment'[collected_amount])", "#,##0.00", "Currency (VND)", "Successful payment events by payment date."),
    ("fct_payment", "Payment Event Count", "DISTINCTCOUNT('fct_payment'[payment_id])", "#,##0", "Payment Events", "Payment-event count; split payments remain separate events."),
    ("fct_payment", "Split Payment Orders", "COUNTROWS(FILTER(VALUES('fct_payment'[order_id]), [Payment Event Count] > 1))", "#,##0", "Orders", "Orders with more than one payment event in the current context."),
    ("fct_return", "Completed Refunds", "SUM('fct_return'[completed_refund])", "#,##0.00", "Currency (VND)", "Completed refunds by return date."),
    ("vw_order_reconciliation", "Collection Variance", "SUM('vw_order_reconciliation'[collection_variance])", "#,##0.00", "Currency (VND)", "Successful collected payments minus expected delivered-sales proxy by order; order-date context."),
    ("vw_order_reconciliation", "Finance Date Note", "\"Payments: payment date; refunds: return date; variance: order date.\"", None, "Report Notes", "Makes distinct event-time semantics visible."),
    ("fct_shipment", "Total Delivered Shipments", "CALCULATE(COUNTROWS('fct_shipment'), FILTER('fct_shipment', 'fct_shipment'[status] = \"delivered\" && NOT(ISBLANK('fct_shipment'[transit_days]))))", "#,##0", "Shipments", "Delivered shipments with a known transit duration."),
    ("fct_shipment", "Late Delivered Shipments", "CALCULATE([Total Delivered Shipments], 'fct_shipment'[late_over_3_days] = TRUE())", "#,##0", "Shipments", "Delivered shipments over the demo three-day threshold."),
    ("fct_shipment", "Late Shipment %", "DIVIDE([Late Delivered Shipments], [Total Delivered Shipments])", "0.0%", "Percentages", "Late shipment rate under the active ship-date role."),
    ("fct_shipment", "Late Shipment % by Delivery Date", "CALCULATE([Late Shipment %], USERELATIONSHIP('dim_date'[date_key], 'fct_shipment'[delivery_date_key]))", "0.0%", "Percentages", "Late shipment rate using the inactive delivery-date role."),
    ("fct_shipment", "P90 Transit Days", "CALCULATE(PERCENTILEX.INC(FILTER('fct_shipment', 'fct_shipment'[status] = \"delivered\" && NOT(ISBLANK('fct_shipment'[transit_days]))), 'fct_shipment'[transit_days], 0.9), USERELATIONSHIP('dim_date'[date_key], 'fct_shipment'[delivery_date_key]))", "0.0 \"days\"", "Transit", "Inclusive 90th percentile for delivered shipments with known duration, by delivery date."),
    ("fct_shipment", "Delivered By Delivery Date", "CALCULATE([Total Delivered Shipments], USERELATIONSHIP('dim_date'[date_key], 'fct_shipment'[delivery_date_key]))", "#,##0", "Shipments", "Delivered shipment count under the inactive delivery-date role."),
    ("fct_weather_daily", "Average Daily Rainfall (mm)", "AVERAGE('fct_weather_daily'[precipitation_mm])", "0.0 \"mm\"", "Weather", "Province-level daily rainfall average."),
    ("fct_weather_daily", "Weather Source", "SELECTEDVALUE('fct_weather_daily'[source], \"Multiple sources\")", None, "Weather", "Source label from the Gold weather fact."),
    ("fct_weather_daily", "Weather Interpretation Note", "\"Weather is synthetic and province-level; association with shipment lateness is not causal.\"", None, "Report Notes", "Provenance and interpretation reminder."),
]

RELATIONSHIPS = [
    ("dim_date", "date_key", "fct_order_item", "order_date_key", True),
    ("dim_customer", "customer_key", "fct_order_item", "customer_key", True),
    ("dim_product", "product_key", "fct_order_item", "product_key", True),
    ("dim_geography", "geography_key", "fct_order_item", "geography_key", True),
    ("dim_date", "date_key", "fct_payment", "payment_date_key", True),
    ("dim_geography", "geography_key", "fct_payment", "geography_key", True),
    ("dim_date", "date_key", "fct_return", "return_date_key", True),
    ("dim_geography", "geography_key", "fct_return", "geography_key", True),
    ("dim_date", "date_key", "fct_shipment", "ship_date_key", True),
    ("dim_date", "date_key", "fct_shipment", "delivery_date_key", False),
    ("dim_geography", "geography_key", "fct_shipment", "geography_key", True),
    ("dim_date", "date_key", "fct_weather_daily", "date_key", True),
    ("dim_geography", "geography_key", "fct_weather_daily", "geography_key", True),
    ("dim_date", "date_key", "vw_order_reconciliation", "order_date_key", True),
    ("dim_geography", "geography_key", "vw_order_reconciliation", "geography_key", True),
]

PAGES = {
    "ExecutiveSales": "Executive Sales",
    "FinanceReconciliation": "Finance & Reconciliation",
    "OperationsWeather": "Operations & Weather",
}


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tmdl_text(value: str) -> str:
    if '"' in value or value.startswith(" ") or value.endswith(" "):
        return '"' + value.replace('"', '""') + '"'
    return value


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]


def write_tmdl_tables() -> None:
    for table, columns in TABLES.items():
        lines = [f"table {table}"]
        if table == "dim_date":
            lines.append("    dataCategory: Time")
        for col, dtype, _, fmt, summarize, hidden, is_key in columns:
            lines += ["", f"    column {col}", f"        dataType: {dtype}", f"        sourceColumn: {col}"]
            if fmt:
                lines.append(f"        formatString: {tmdl_text(fmt)}")
            if summarize:
                lines.append(f"        summarizeBy: {summarize}")
            if hidden:
                lines.append("        isHidden")
            if is_key:
                lines.append("        isKey")
        for measure_table, name, dax, fmt, folder, description in MEASURES:
            if measure_table != table:
                continue
            lines += ["", f"    /// {description}", f"    measure '{name}' = {dax}"]
            if fmt:
                lines.append(f"        formatString: {tmdl_text(fmt)}")
            if folder:
                lines.append(f'        displayFolder: "{folder}"')
        m_columns = ",\n            ".join(f'{{"{col}", {pq_type}}}' for col, _, pq_type, _, _, _, _ in columns)
        m_query = (
            "let\n"
            f'    Sheet = GoldWorkbook{{[Item = "{table}", Kind = "Sheet"]}}[Data],\n'
            "    PromotedHeaders = Table.PromoteHeaders(Sheet, [PromoteAllScalars = true]),\n"
            "    TypedColumns = Table.TransformColumnTypes(\n"
            "        PromotedHeaders,\n"
            "        {\n            " + m_columns + "\n        },\n"
            '        "en-US"\n'
            "    )\n"
            "in\n"
            "    TypedColumns"
        )
        lines += ["", f"    partition {table} = m", "        mode: import", "        source ="]
        lines += ["            " + line if line else "" for line in m_query.splitlines()]
        (TABLES_DIR / f"{table}.tmdl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def remove_orphaned_local_date_tables() -> None:
    """Drop Desktop-generated auto-date tables after their source columns are regenerated.

    This model uses the explicit dim_date table. A prior Desktop save can leave
    hidden LocalDateTable files behind after this generator replaces source
    tables without their variation references. Those orphaned tables make the
    PBIP fail to load. With auto date/time disabled below, they are unnecessary.
    """
    tables_root = TABLES_DIR.resolve()
    candidates = list(TABLES_DIR.glob("LocalDateTable_*.tmdl"))
    sources = [path for path in TABLES_DIR.glob("*.tmdl") if path not in candidates]
    source_text = [(path, path.read_text(encoding="utf-8")) for path in sources]
    for table_path in candidates:
        if not table_path.resolve().is_relative_to(tables_root):
            raise ValueError(f"Refusing to remove a local date table outside {tables_root}: {table_path}")
        if any(table_path.stem in text for _, text in source_text):
            continue
        table_path.unlink()


def write_model() -> None:
    for directory in (TABLES_DIR, ROLES_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    (MODEL / "definition.pbism").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.0",
        "settings": {"qnaEnabled": False},
    }, indent=2) + "\n", encoding="utf-8")
    (MODEL_DEF / "database.tmdl").write_text(
        "database DataForge\n    compatibilityLevel: 1606\n    compatibilityMode: powerBI\n", encoding="utf-8")
    (MODEL_DEF / "model.tmdl").write_text(
        "model Model\n"
        "    culture: en-US\n"
        "    defaultPowerBIDataSourceVersion: powerBI_V3\n"
        "\n"
        "    annotation __PBI_TimeIntelligenceEnabled = 0\n",
        encoding="utf-8",
    )
    (MODEL_DEF / "expressions.tmdl").write_text(
        'expression GoldWorkbookPath = "__DATAFORGE_LOCAL_WORKBOOK_PATH__" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
        "expression GoldWorkbook =\n    Excel.Workbook(File.Contents(GoldWorkbookPath), null, true)\n",
        encoding="utf-8",
    )
    (ROLES_DIR / "South_Region_Viewer.tmdl").write_text(
        "role South_Region_Viewer\n"
        "    modelPermission: read\n\n"
        "    tablePermission dim_geography = 'dim_geography'[region] = \"South\"\n"
        "    tablePermission dim_customer = 'dim_customer'[customer_region] = \"South\"\n",
        encoding="utf-8",
    )
    rel_lines = []
    for dim, dim_key, fact, fact_key, active in RELATIONSHIPS:
        rel_name = uuid5(NAMESPACE_URL, f"DataForge::{dim}.{dim_key}->{fact}.{fact_key}")
        rel_lines += [
            f"relationship {rel_name}",
            f"    fromColumn: {fact}.{fact_key}",
            f"    toColumn: {dim}.{dim_key}",
            f"    isActive: {str(active).lower()}",
            "    crossFilteringBehavior: oneDirection",
            "",
        ]
    (MODEL_DEF / "relationships.tmdl").write_text("\n".join(rel_lines), encoding="utf-8")
    write_tmdl_tables()
    remove_orphaned_local_date_tables()

    write_json(MODEL / ".platform", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": "DataForge"},
        "config": {"version": "2.0", "logicalId": str(uuid5(NAMESPACE_URL, "DataForge.P5.SemanticModel"))},
    })


def col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def measure(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def projection(field: dict, query_ref: str, native: str, active: bool = False,
               display_name: str | None = None) -> dict:
    result = {"field": field, "queryRef": query_ref, "nativeQueryRef": native}
    if active:
        result["active"] = True
    if display_name:
        result["displayName"] = display_name
    return result


def card(title: str, entity: str, name: str, pos: tuple[int, int, int, int, int],
         *, display_name: str | None = None, display_units: int | None = None,
         precision: int | None = None) -> dict:
    objects = None
    if display_units is not None or precision is not None:
        properties = {}
        if display_units is not None:
            properties["labelDisplayUnits"] = {"expr": {"Literal": {"Value": f"{display_units}D"}}}
        if precision is not None:
            properties["labelPrecision"] = {"expr": {"Literal": {"Value": f"{precision}L"}}}
        objects = {"value": [{"properties": properties, "selector": {"id": "default"}}]}
    projection_name = display_name or title
    return visual(
        "cardVisual", title,
        {"Data": {"projections": [projection(measure(entity, name), f"{entity}.{name}", name, display_name=projection_name)]}},
        pos, objects=objects, show_title=False,
    )


def slicer(title: str, entity: str, name: str, pos: tuple[int, int, int, int, int]) -> dict:
    return visual("slicer", title, {"Values": {"projections": [projection(col(entity, name), f"{entity}.{name}", name, True)]}}, pos)


def chart(vtype: str, title: str, category_entity: str, category: str, measure_entity: str, name: str,
          pos: tuple[int, int, int, int, int]) -> dict:
    return visual(vtype, title, {
        "Category": {"projections": [projection(col(category_entity, category), f"{category_entity}.{category}", category, True)]},
        "Y": {"projections": [projection(measure(measure_entity, name), f"{measure_entity}.{name}", name)]},
    }, pos)


def table(title: str, fields: list[tuple[str, str, bool]], pos: tuple[int, int, int, int, int]) -> dict:
    projections = []
    display_names = {
        ("fct_payment", "Payment Event Count"): "Payment Events",
        ("fct_payment", "Collected Payments"): "Collected (VND)",
    }
    for entity, prop, is_measure in fields:
        field = measure(entity, prop) if is_measure else col(entity, prop)
        projections.append(projection(field, f"{entity}.{prop}", prop, True,
                                      display_name=display_names.get((entity, prop))))
    return visual("tableEx", title, {"Values": {"projections": projections}}, pos)


def visual(vtype: str, title: str, query_state: dict, pos: tuple[int, int, int, int, int],
           *, objects: dict | None = None, show_title: bool = True) -> dict:
    x, y, width, height, z = pos
    visual_id = stable_id(f"{title}|{vtype}|{x}|{y}")
    visual_body = {
        "visualType": vtype,
        "query": {"queryState": query_state},
        "drillFilterOtherVisuals": True,
        "visualContainerObjects": {"title": [{"properties": {
            "show": {"expr": {"Literal": {"Value": str(show_title).lower()}}},
            **({"text": {"expr": {"Literal": {"Value": "'" + title.replace("'", "''") + "'"}}}} if show_title else {}),
        }}]},
    }
    if objects:
        visual_body["objects"] = objects
    return {
        "_name": visual_id,
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.9.0/schema.json",
        "name": visual_id,
        "position": {"x": x, "y": y, "z": z, "width": width, "height": height, "tabOrder": z},
        "visual": visual_body,
    }


def page_visuals() -> dict[str, list[dict]]:
    return {
        "ExecutiveSales": [
            card("Notice", "fct_order_item", "Demo Data Notice", (20,10,1240,80,1000)),
            slicer("Order date", "dim_date", "calendar_date", (20,95,220,60,2000)),
            slicer("Order region", "dim_geography", "region", (250,95,160,60,3000)),
            slicer("Customer segment", "dim_customer", "segment", (420,95,200,60,4000)),
            card("Sales Proxy", "fct_order_item", "Fulfilled Sales Proxy", (20,160,210,75,5000)),
            card("Delivered Orders", "fct_order_item", "Delivered Orders", (240,160,230,75,6000)),
            card("Avg Order M VND", "fct_order_item", "Average Order Value", (480,160,240,75,7000), display_name="Avg Order M VND", display_units=1_000_000, precision=2),
            card("Gross Margin Proxy (VND)", "fct_order_item", "Gross Margin Proxy", (730,160,340,75,8000)),
            card("Margin Proxy", "fct_order_item", "Margin Proxy %", (1080,160,180,75,9000)),
            chart("lineChart", "Sales Proxy by Order Month", "dim_date", "month_start", "fct_order_item", "Fulfilled Sales Proxy", (20,245,780,425,10000)),
            chart("clusteredBarChart", "Sales Proxy by Category", "dim_product", "category", "fct_order_item", "Fulfilled Sales Proxy", (820,245,440,425,11000)),
        ],
        "FinanceReconciliation": [
            slicer("Order / event date", "dim_date", "calendar_date", (20,20,220,64,1000)),
            slicer("Order region", "dim_geography", "region", (250,20,160,64,2000)),
            card("Finance date roles", "vw_order_reconciliation", "Finance Date Note", (425,20,835,64,3000)),
            card("Collections (VND)", "fct_payment", "Collected Payments", (20,100,250,85,4000)),
            card("Completed Refunds (VND)", "fct_return", "Completed Refunds", (280,100,320,85,5000)),
            card("Collection Variance (VND)", "vw_order_reconciliation", "Collection Variance", (610,100,320,85,6000)),
            card("Split-Payment Orders", "fct_payment", "Split Payment Orders", (940,100,320,85,7000)),
            table("Order-level reconciliation (order-date context)", [
                ("vw_order_reconciliation","order_id",False),
                ("vw_order_reconciliation","expected_collection_proxy",False),
                ("vw_order_reconciliation","collected",False),
                ("vw_order_reconciliation","collection_variance",False),
            ], (20,205,680,470,8000)),
            table("Payment events grouped by order", [
                ("fct_payment","order_id",False),
                ("fct_payment","Payment Event Count",True),
                ("fct_payment","Collected Payments",True),
            ], (720,205,540,470,9000)),
        ],
        "OperationsWeather": [
            card("Synthetic weather | descriptive, not causal", "fct_weather_daily", "Weather Interpretation Note", (20,10,1240,75,1000)),
            slicer("Calendar date (see role notes)", "dim_date", "calendar_date", (20,90,220,64,2000)),
            slicer("Province region", "dim_geography", "region", (250,90,160,64,3000)),
            card("Late Ship (%)", "fct_shipment", "Late Shipment % by Delivery Date", (425,90,175,64,4000)),
            card("P90 Transit", "fct_shipment", "P90 Transit Days", (610,90,155,64,5000)),
            card("Return Line Rate (%)", "fct_order_item", "Return Line Rate", (775,90,255,64,6000)),
            card("Weather Source", "fct_weather_daily", "Weather Source", (1040,90,220,64,7000)),
            card("Date role notes", "fct_order_item", "Return Line Rate Date Rule", (20,165,1240,80,8000)),
            chart("clusteredBarChart", "P90 Transit Days by Carrier", "fct_shipment", "carrier", "fct_shipment", "P90 Transit Days", (20,255,380,210,9000)),
            chart("clusteredBarChart", "Return Line Rate by Product Category", "dim_product", "category", "fct_order_item", "Return Line Rate", (420,255,400,210,10000)),
            chart("lineChart", "Late Shipment % by Delivery Month", "dim_date", "month_start", "fct_shipment", "Late Shipment % by Delivery Date", (840,255,420,210,11000)),
            chart("lineChart", "Average Rainfall by Observation Month", "dim_date", "month_start", "fct_weather_daily", "Average Daily Rainfall (mm)", (20,485,600,225,12000)),
            chart("clusteredBarChart", "Average Rainfall by Province", "dim_geography", "province", "fct_weather_daily", "Average Daily Rainfall (mm)", (640,485,620,225,13000)),
        ],
    }


def write_report() -> None:
    (PROJECT / "DataForge.pbip").write_text(json.dumps({
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
        "version": "1.0",
        "artifacts": [{"report": {"path": "DataForge.Report"}}],
        "settings": {"enableAutoRecovery": True},
    }, indent=2) + "\n", encoding="utf-8")
    write_json(REPORT / "definition.pbir", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": "../DataForge.SemanticModel"}},
    })
    write_json(REPORT_DEF / "version.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    })
    write_json(REPORT_DEF / "report.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.3.0/schema.json",
        "themeCollection": {
            "customTheme": {
                "name": "DataForgeTheme.json",
                "reportVersionAtImport": {"visual": "2.9.0", "report": "3.3.0", "page": "2.1.0"},
                "type": "RegisteredResources",
            }
        },
        "resourcePackages": [{
            "name": "RegisteredResources",
            "type": "RegisteredResources",
            "items": [{"name": "DataForgeTheme.json", "path": "DataForgeTheme.json", "type": "CustomTheme"}],
        }],
    })
    write_json(REPORT / ".platform", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": "DataForge"},
        "config": {"version": "2.0", "logicalId": str(uuid5(NAMESPACE_URL, "DataForge.P5.Report"))},
    })
    theme_path = REPORT / "StaticResources" / "RegisteredResources" / "DataForgeTheme.json"
    write_json(theme_path, {
        "name": "DataForge Light",
        "dataColors": ["#1F4E79", "#2F75B5", "#70AD47", "#ED7D31", "#A5A5A5", "#FFC000"],
        "background": "#FFFFFF",
        "foreground": "#243447",
        "tableAccent": "#1F4E79",
    })
    pages = page_visuals()
    page_ids = {key: "ReportSection" + stable_id(f"DataForge page {key}") for key in PAGES}
    page_root = REPORT_DEF / "pages"
    page_root.mkdir(parents=True, exist_ok=True)
    allowed_pages = set(page_ids.values())
    for stale_page in (item for item in page_root.iterdir() if item.is_dir() and item.name not in allowed_pages):
        if not stale_page.resolve().is_relative_to(page_root.resolve()):
            raise ValueError(f"Refusing to clean a PBIR page outside the report folder: {stale_page}")
        for child in sorted(stale_page.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        stale_page.rmdir()
    write_json(REPORT_DEF / "pages" / "pages.json", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [page_ids[key] for key in PAGES],
        "activePageName": page_ids["ExecutiveSales"],
    })
    for page_key, display_name in PAGES.items():
        page_dir = REPORT_DEF / "pages" / page_ids[page_key]
        visuals_dir = page_dir / "visuals"
        if visuals_dir.exists():
            # Regeneration must not leave obsolete visuals from prior layouts.
            if not visuals_dir.resolve().is_relative_to(P5.resolve()):
                raise ValueError(f"Refusing to clean PBIR folder outside P5: {visuals_dir}")
            for child in sorted(visuals_dir.rglob("*"), key=lambda item: len(item.parts), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            visuals_dir.rmdir()
        write_json(page_dir / "page.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json",
            "name": page_ids[page_key],
            "displayName": display_name,
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
        })
        for spec in pages[page_key]:
            visual_id = spec["name"]
            visual = {key: value for key, value in spec.items() if key != "_name"}
            write_json(page_dir / "visuals" / visual_id / "visual.json", visual)


def write_reference_files() -> None:
    with (P5 / "RELATIONSHIPS.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["Dimension","DimensionKey","Fact","FactKey","Cardinality","FilterDirection","Active"])
        for dim, dim_key, fact, fact_key, active in RELATIONSHIPS:
            writer.writerow([dim,dim_key,fact,fact_key,"1_to_many","single","yes" if active else "no"])
    with (P5 / "DAX_MEASURES.dax").open("w", encoding="utf-8") as stream:
        stream.write("// Manual reference. The PBIP TMDL model includes these measures.\n\n")
        for table, name, dax, fmt, folder, description in MEASURES:
            stream.write(f"// {table}: {description}\n{name} = {dax}\n\n")
    (P5 / "REPORT_PAGE_SPEC.md").write_text(
        """# Report page and control specification

| Page | Visuals | Date role | Supported slicers |
|---|---|---|---|
| Executive Sales | Synthetic/proxy banner; fulfilled-sales and margin KPI cards; delivered orders; average order value card (VND millions, 2 decimals); monthly fulfilled-sales line; category bar | Order date | Date, order region, customer segment, product/category |
| Finance & Reconciliation | Payments, refunds, variance and split-payment-order cards; order-level reconciliation table; payment-event-by-order table | Payments: payment date; refunds: return date; variance: order date | Date and geography; no customer/product path for these facts |
| Operations & Weather | Late-delivery, P90 and return-line-rate cards; P90 by carrier; return-line-rate by category; late deliveries by delivery month; rainfall by observation month and province; weather-source label | Late/P90 by delivery date; weather by observation date; return-line-rate uses an order-date cohort and includes eventual completed returns | Date and region |

The inventory snapshot is deliberately omitted from the semantic model because it has no regional key. Fact tables remain at separate grains. Weather/late-shipment association is descriptive, not causal.
""", encoding="utf-8")
    (P5 / "README.md").write_text(
        """# DataForge Power BI source pack

This is a local, synthetic-only PBIP/PBIR/TMDL project. The v1.0-local P6.2 result is **GO LOCAL**: three report pages rendered in Power BI Desktop and the accepted source passed structural and layout validation. The Import model reads a generated Gold workbook through a configurable `GoldWorkbookPath` sentinel. No `.pbix`, credentials, PostgreSQL connection string or published Power BI Service report is included.

## Input and refresh

The model imports ten sheets from the eleven-sheet Gold export. The project ships with the local workbook path unconfigured; set it before opening or refreshing the PBIP.

Generate the workbook and CSV snapshots with:

```powershell
.\\.venv\\Scripts\\python.exe .\\scripts\\export_powerbi_gold.py --excel
```

Before opening the report, validate and configure the workbook path with:

```powershell
.\\.venv\\Scripts\\python.exe .\\dashboards\\P5\\configure_workbook_path.py `
  --project .\\dashboards\\P5\\DataForge\\DataForge.pbip `
  --workbook .\\data\\powerbi_gold_export\\DataForgeGold.xlsx
.\\.venv\\Scripts\\python.exe .\\dashboards\\P5\\validate_source_pack.py `
  --project .\\dashboards\\P5\\DataForge\\DataForge.pbip `
  --workbook .\\data\\powerbi_gold_export\\DataForgeGold.xlsx
```

The configurator requires the workbook's sibling `manifest.json`, checks the synthetic marker, workbook SHA-256, sheet names and row counts, saves a timestamped TMDL backup and atomically replaces the `GoldWorkbookPath` parameter. On relocation, copy the full export folder and pass the new workbook path. Power Query uses the explicit local absolute path; relative path behavior is not assumed. No password or database credential is stored in the project.

`fct_inventory_snapshot` is intentionally **not imported**. It has no geography key and cannot be correctly filtered by the regional RLS role.

## Open and validate

After configuring the workbook path, open `DataForge/DataForge.pbip` in Power BI Desktop. The project contains `Executive Sales`, `Finance & Reconciliation`, and `Operations & Weather` PBIR pages; model definitions and RLS role are in the TMDL semantic model folder. Use `RELATIONSHIPS.csv`, `DAX_MEASURES.dax`, and `REPORT_PAGE_SPEC.md` as review inventories.

The PBIR package uses report content version `2.0.0`, `ReportSection`-prefixed page IDs, a registered local theme resource and the companion `.platform` metadata. If Desktop still opens only a blank `Page 1`, save a minimal PBIR project from that Desktop build and compare its generated page/report metadata before changing this package. This project does not use PBIR-Legacy `report.json` content.

The `South_Region_Viewer` role filters both `dim_geography[region] = "South"` and `dim_customer[customer_region] = "South"`. It is a model-level demonstration, not production authorization. Product master rows are not region-protected. Inventory is absent from the model and every page.

The Executive Sales page has date, order-region and customer-segment slicers; customer-segment filtering reaches order-item measures through the SCD2 customer surrogate relationship. The model disables automatic date/time and marks `dim_date[calendar_date]` as the unique date key, avoiding hidden local date tables.

Date roles are explicit: fulfilled sales and collection variance use order date; payments use payment date; refunds use return date; the active shipment relationship uses ship date, while late/P90 measures activate delivery date; weather uses observation date. The Return Line Rate uses an order-date cohort of delivered item IDs, then counts any associated completed return events after removing the return-date filter. It is a line rate, not a unit-return rate. Weather visuals are province-level and non-causal. Fulfilled sales is a proxy, not recognized revenue.

Average Order Value retains an unrounded `DIVIDE` calculation and a whole-VND base formatString (`#,##0`). The Executive card explicitly overrides visual display units to Millions with two decimals, so the current SQL value `1,961,999.0249609984` and Query View value `1,961,999.0250000000` both appear as `1.96M` VND. No epsilon or artificial adjustment is applied.

The model carries its date-table metadata in TMDL; `dim_date[calendar_date]` is unique and continuous from 2022-01-01 through 2022-05-20 in this fixture.

## Verification state

`validate_source_pack.py` verifies workbook/hash/row counts, the local path parameter, TMDL date settings, model references, KPI labels, RLS filters, page structure, AOV formatting and absence of embedded credentials. The P6.2 GO LOCAL acceptance, three current-source screenshots and remaining limitations are summarized in `docs/releases/v1.0-local.md`.
""", encoding="utf-8")


def main() -> None:
    assert GOLD_FILE.is_file(), f"Gold workbook not found: {GOLD_FILE}"
    MODEL_DEF.mkdir(parents=True, exist_ok=True)
    (MODEL_DEF / "tables").mkdir(exist_ok=True)
    (MODEL_DEF / "roles").mkdir(exist_ok=True)
    (REPORT_DEF / "pages").mkdir(parents=True, exist_ok=True)
    write_model()
    write_report()
    write_reference_files()
    print(f"Generated {PROJECT}")
    print(f"Tables: {len(TABLES)}; relationships: {len(RELATIONSHIPS)}; measures: {len(MEASURES)}; report pages: {len(PAGES)}")


if __name__ == "__main__":
    main()
