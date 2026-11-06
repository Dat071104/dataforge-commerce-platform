"""Credential-free structural checks for the local DataForge Power BI source pack."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
P5 = Path(__file__).resolve().parent
PROJECT = P5 / "DataForge"
MODEL_DEF = PROJECT / "DataForge.SemanticModel" / "definition"
REPORT_DEF = PROJECT / "DataForge.Report" / "definition"
EXPORT = ROOT / "data" / "powerbi_gold_export"
WORKBOOK = EXPORT / "DataForgeGold.xlsx"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


WORKBOOK_PATH_SENTINEL = "__DATAFORGE_LOCAL_WORKBOOK_PATH__"
CARD_DISPLAY_NAMES = {
    "Gross Margin Proxy": "Gross Margin Proxy (VND)",
    "Fulfilled Sales Proxy": "Sales Proxy",
    "Average Order Value": "Avg Order M VND",
    "Demo Data Notice": "Notice",
    "Delivered Orders": "Delivered Orders",
    "Margin Proxy %": "Margin Proxy",
    "Collected Payments": "Collections (VND)",
    "Split Payment Orders": "Split-Payment Orders",
    "Finance Date Note": "Finance date roles",
    "Completed Refunds": "Completed Refunds (VND)",
    "Collection Variance": "Collection Variance (VND)",
    "Weather Interpretation Note": "Synthetic weather | descriptive, not causal",
    "P90 Transit Days": "P90 Transit",
    "Return Line Rate Date Rule": "Date role notes",
    "Late Shipment % by Delivery Date": "Late Ship (%)",
    "Weather Source": "Weather Source",
    "Return Line Rate": "Return Line Rate (%)",
}


def resolve_project_dir(project_arg: Path) -> Path:
    project_path = project_arg.expanduser().resolve(strict=True)
    if project_path.is_file():
        if project_path.suffix.casefold() != ".pbip":
            fail(f"expected a .pbip file or project directory: {project_path}")
        return project_path.parent
    if project_path.is_dir():
        candidates = sorted(project_path.glob("*.pbip"))
        if len(candidates) != 1:
            fail(f"expected exactly one .pbip file in {project_path}; found {len(candidates)}")
        return project_path
    fail(f"PBIP project does not exist: {project_path}")


def load_model_tables(model_def: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, list[str]]]:
    columns: dict[str, set[str]] = {}
    measures: dict[str, set[str]] = {}
    measure_expressions: dict[str, list[str]] = {}
    for path in (model_def / "tables").glob("*.tmdl"):
        # Desktop may materialize hidden date-table templates after the user
        # marks dim_date as the model date table. They are generated objects,
        # not imported Gold tables in the source pack.
        if path.stem.startswith(("LocalDateTable_", "DateTableTemplate_")):
            continue
        text = path.read_text(encoding="utf-8")
        table = path.stem
        columns[table] = set(re.findall(r"^[ \t]+column ([A-Za-z0-9_]+)$", text, re.MULTILINE))
        found = re.findall(r"^[ \t]+measure '([^']+)' = (.+)$", text, re.MULTILINE)
        measures[table] = {name for name, _ in found}
        measure_expressions[table] = [expression for _, expression in found]
    return columns, measures, measure_expressions


def validate(
    project_path: Path = PROJECT,
    workbook_path: Path | None = None,
) -> tuple[int, int, int, str]:
    project = resolve_project_dir(project_path)
    p5 = project.parent
    model_def = project / "DataForge.SemanticModel" / "definition"
    report_def = project / "DataForge.Report" / "definition"
    workbook = (workbook_path or (ROOT / "data" / "powerbi_gold_export" / "DataForgeGold.xlsx"))
    workbook = workbook.expanduser().resolve()
    export = workbook.parent
    if not workbook.is_file():
        fail(f"missing synthetic Gold workbook: {workbook}")
    model_text = (model_def / "model.tmdl").read_text(encoding="utf-8")
    if not re.search(r"^\s*annotation __PBI_TimeIntelligenceEnabled = 0\s*$", model_text, re.MULTILINE):
        fail("the explicit dim_date model must disable automatic local date tables")
    orphaned_date_tables = sorted((model_def / "tables").glob("LocalDateTable_*.tmdl"))
    if orphaned_date_tables:
        fail(f"stale Desktop-generated LocalDateTable files remain: {[path.name for path in orphaned_date_tables]}")
    manifest = json.loads((export / "manifest.json").read_text(encoding="utf-8"))
    if "synthetic" not in manifest.get("data_classification", "").casefold():
        fail("Gold export is not marked synthetic")
    workbook_meta = manifest.get("excel_workbook", {})
    if workbook_meta.get("file") != workbook.name:
        fail("manifest workbook file does not match the model input")
    workbook_digest = hashlib.sha256(workbook.read_bytes()).hexdigest()
    if workbook_digest != workbook_meta.get("sha256"):
        fail("workbook SHA-256 does not match export manifest")

    with zipfile.ZipFile(WORKBOOK) as archive:
        workbook_xml = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    sheets = {node.attrib["name"] for node in workbook_xml.findall("x:sheets/x:sheet", ns)}

    expressions_path = model_def / "expressions.tmdl"
    expressions_text = expressions_path.read_text(encoding="utf-8")
    parameter = re.findall(
        r'(?m)^expression GoldWorkbookPath = ("(?:[^"]|"")*") meta '
        r'\[IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true\]$',
        expressions_text,
    )
    if len(parameter) != 1:
        fail(f"expected one GoldWorkbookPath parameter in {expressions_path}")
    configured_path = parameter[0][1:-1].replace('""', '"')
    if configured_path == WORKBOOK_PATH_SENTINEL:
        workbook_path_status = "unconfigured"
        if workbook_path is not None:
            fail("PBIP workbook path is unconfigured; run configure_workbook_path.py before validating relocation")
    else:
        try:
            configured = Path(configured_path).expanduser().resolve()
        except OSError as exc:
            fail(f"invalid GoldWorkbookPath value: {exc}")
        if os.path.normcase(str(configured)) != os.path.normcase(str(workbook)):
            fail(f"GoldWorkbookPath does not match selected workbook: {configured} != {workbook}")
        workbook_path_status = "configured"

    columns, measures, measure_expressions = load_model_tables(model_def)
    if len(columns) != 10:
        fail(f"expected 10 model tables (inventory intentionally excluded), found {len(columns)}")
    aov_tmdl = (model_def / "tables" / "fct_order_item.tmdl").read_text(encoding="utf-8")
    aov_match = re.search(
        r"measure 'Average Order Value' = ([^\r\n]+)\r?\n[ \t]+formatString: ([^\r\n]+)",
        aov_tmdl,
    )
    if not aov_match or aov_match.group(1).strip() != "DIVIDE([Fulfilled Sales Proxy], [Delivered Orders])":
        fail("Average Order Value must remain the unrounded fulfilled-sales/order-count DIVIDE")
    if aov_match.group(2).strip() != "#,##0":
        fail("Average Order Value must display at whole-VND precision (#,##0)")
    date_table = (model_def / "tables" / "dim_date.tmdl").read_text(encoding="utf-8")
    if "dataCategory: Time" not in date_table:
        fail("dim_date must retain the Desktop date-table metadata")
    if len(re.findall(r"^[ \t]+isKey$", date_table, re.MULTILINE)) != 1:
        fail("dim_date must have exactly one key column")
    date_column = re.search(
        r"^[ \t]+column calendar_date\s*(.*?)(?=^[ \t]+column |^[ \t]+partition )",
        date_table, re.MULTILINE | re.DOTALL,
    )
    if not date_column or not re.search(r"^[ \t]+isKey$", date_column.group(1), re.MULTILINE):
        fail("dim_date[calendar_date] must be marked as the date key")
    if "fct_inventory_snapshot" in columns:
        fail("global inventory must not be in the regional RLS model")
    if not set(columns).issubset(sheets):
        fail(f"workbook is missing model sheets: {sorted(set(columns) - sheets)}")

    exported = {item["table"]: item for item in manifest["tables"]}
    for table, columns_in_model in columns.items():
        item = exported.get(table)
        if not item:
            fail(f"manifest is missing exported table {table}")
        csv_path = export / item["file"]
        payload = csv_path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != item["sha256"]:
            fail(f"CSV hash mismatch for {table}")
        with csv_path.open(newline="", encoding="utf-8-sig") as stream:
            reader = csv.reader(stream)
            headers = set(next(reader))
            rows = sum(1 for _ in reader)
        if headers != columns_in_model:
            fail(f"model columns do not match Gold CSV headers for {table}")
        if rows != item["row_count"]:
            fail(f"row count mismatch for {table}: CSV={rows}, manifest={item['row_count']}")

    all_measures = set().union(*measures.values())
    for table, expressions in measure_expressions.items():
        for expression in expressions:
            for referenced_table, column in re.findall(r"'([^']+)'\[([^\]]+)\]", expression):
                if referenced_table not in columns or column not in columns[referenced_table]:
                    fail(f"unresolved DAX column reference {referenced_table}[{column}]")
            for reference in re.findall(r"(?<!')\[([^\]]+)\]", expression):
                if reference not in all_measures:
                    fail(f"unresolved DAX measure reference [{reference}]")

    relationships_path = p5 / "RELATIONSHIPS.csv"
    with relationships_path.open(newline="", encoding="utf-8") as stream:
        relationship_rows = list(csv.DictReader(stream))
    if len(relationship_rows) != 15:
        fail(f"expected 15 relationships, found {len(relationship_rows)}")
    if sum(row["Active"] == "no" for row in relationship_rows) != 1:
        fail("the delivery-date relationship must be the only inactive relationship")
    if any(row["Fact"] == "fct_inventory_snapshot" for row in relationship_rows):
        fail("inventory relationship found in the regional RLS model")
    tmdl_relationships = (model_def / "relationships.tmdl").read_text(encoding="utf-8")
    tmdl_pairs = set(re.findall(
        r"fromColumn: ([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)\s+toColumn: ([A-Za-z0-9_]+)\.([A-Za-z0-9_]+)",
        tmdl_relationships,
    ))
    csv_pairs = {(r["Fact"], r["FactKey"], r["Dimension"], r["DimensionKey"])
                 for r in relationship_rows}
    if tmdl_pairs != csv_pairs:
        fail("RELATIONSHIPS.csv and TMDL relationship definitions differ")

    role = (model_def / "roles" / "South_Region_Viewer.tmdl").read_text(encoding="utf-8")
    for expected in (
        "'dim_geography'[region] = \"South\"",
        "'dim_customer'[customer_region] = \"South\"",
    ):
        if expected not in role:
            fail(f"South_Region_Viewer is missing row filter {expected}")

    pages = list((report_def / "pages").glob("*/page.json"))
    expected_pages = {"Executive Sales", "Finance & Reconciliation", "Operations & Weather"}
    actual_pages = {json.loads(path.read_text(encoding="utf-8"))["displayName"] for path in pages}
    if actual_pages != expected_pages:
        fail(f"report page names do not match: {actual_pages}")
    if any(not path.parent.name.startswith("ReportSection") for path in pages):
        fail("PBIR page folders must use the Desktop ReportSection ID prefix")
    page_ids = {path.parent.name for path in pages}
    pages_metadata = json.loads((report_def / "pages" / "pages.json").read_text(encoding="utf-8"))
    if set(pages_metadata.get("pageOrder", [])) != page_ids:
        fail("pages.json pageOrder does not match the page folders")
    if pages_metadata.get("activePageName") not in page_ids:
        fail("pages.json activePageName does not match an existing page")
    for path in pages:
        page_name = json.loads(path.read_text(encoding="utf-8"))["name"]
        if page_name != path.parent.name:
            fail(f"page.json name does not match its folder: {path}")
    version = json.loads((report_def / "version.json").read_text(encoding="utf-8"))
    if version.get("version") != "2.0.0":
        fail(f"expected PBIR report content version 2.0.0, found {version.get('version')}")
    report = json.loads((report_def / "report.json").read_text(encoding="utf-8"))
    theme = report.get("themeCollection", {}).get("customTheme", {})
    theme_name = theme.get("name")
    resources = report.get("resourcePackages", [])
    registered_names = {
        item.get("name")
        for package in resources
        if package.get("type") == "RegisteredResources"
        for item in package.get("items", [])
    }
    if theme_name != "DataForgeTheme.json" or theme_name not in registered_names:
        fail("PBIR custom theme must be registered in report.json")
    if not (project / "DataForge.Report" / "StaticResources" / "RegisteredResources" / theme_name).is_file():
        fail("PBIR registered theme resource is missing")
    for item_path, expected_type in ((project / "DataForge.Report" / ".platform", "Report"),
                                     (project / "DataForge.SemanticModel" / ".platform", "SemanticModel")):
        platform = json.loads(item_path.read_text(encoding="utf-8"))
        if platform.get("metadata", {}).get("type") != expected_type:
            fail(f"invalid .platform item type in {item_path}")
    visual_files = list((report_def / "pages").rglob("visual.json"))
    if len(visual_files) != 33:
        fail(f"expected 33 PBIR visuals across three pages, found {len(visual_files)}")
    for path in visual_files:
        document = json.loads(path.read_text(encoding="utf-8"))
        visual_body = document.get("visual", {})
        if visual_body.get("visualType") == "cardVisual":
            projections = visual_body.get("query", {}).get("queryState", {}).get("Data", {}).get("projections", [])
            if any(not projection.get("displayName") for projection in projections):
                fail(f"cardVisual must use concise explicit projection labels: {path}")
            if len(projections) != 1:
                fail(f"each cardVisual must contain exactly one projection: {path}")
            measure = projections[0].get("field", {}).get("Measure", {}).get("Property")
            expected_label = CARD_DISPLAY_NAMES.get(measure)
            if expected_label and projections[0].get("displayName") != expected_label:
                fail(f"card label for {measure} must be {expected_label!r}: {path}")
            if len(projections[0].get("displayName", "")) > 72:
                fail(f"cardVisual label is too long to remain readable: {path}")

        def visit(node: object) -> None:
            if isinstance(node, dict):
                for kind in ("Column", "Measure"):
                    ref = node.get(kind)
                    if isinstance(ref, dict) and "Expression" in ref and "Property" in ref:
                        entity = ref["Expression"]["SourceRef"]["Entity"]
                        prop = ref["Property"]
                        if entity not in columns:
                            fail(f"visual references unknown table {entity}: {path}")
                        if kind == "Column" and prop not in columns[entity]:
                            fail(f"visual references unknown column {entity}[{prop}]: {path}")
                        if kind == "Measure" and prop not in measures[entity]:
                            fail(f"visual references unknown measure {entity}[{prop}]: {path}")
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(document)
        text = path.read_text(encoding="utf-8").casefold()
        if "fct_inventory_snapshot" in text:
            fail(f"inventory visual reference found: {path}")

    payment_event_tables = []
    for path in visual_files:
        document = json.loads(path.read_text(encoding="utf-8"))
        visual_body = document.get("visual", {})
        if visual_body.get("visualType") != "tableEx":
            continue
        projections = visual_body.get("query", {}).get("queryState", {}).get("Values", {}).get("projections", [])
        measure_names = {
            projection.get("field", {}).get("Measure", {}).get("Property")
            for projection in projections
        }
        if "Payment Event Count" in measure_names:
            payment_event_tables.append(projections)
    if len(payment_event_tables) != 1:
        fail(f"expected one payment-events table visual, found {len(payment_event_tables)}")
    payment_projection_labels = {
        projection.get("field", {}).get("Measure", {}).get("Property"): projection
        for projection in payment_event_tables[0]
        if "Measure" in projection.get("field", {})
    }
    for measure, label in (("Payment Event Count", "Payment Events"),
                           ("Collected Payments", "Collected (VND)")):
        projection = payment_projection_labels.get(measure)
        if not projection or projection.get("active") is not True:
            fail(f"payment-events table must activate {measure}")
        if projection.get("displayName") != label:
            fail(f"payment-events table label for {measure} must be {label!r}")

    aov_visuals = []
    for path in visual_files:
        document = json.loads(path.read_text(encoding="utf-8"))
        projections = document.get("visual", {}).get("query", {}).get("queryState", {}).get("Data", {}).get("projections", [])
        if any(
            p.get("field", {}).get("Measure", {}).get("Property") == "Average Order Value"
            for p in projections
        ):
            aov_visuals.append(document)
    if len(aov_visuals) != 1:
        fail(f"expected one Average Order Value card, found {len(aov_visuals)}")
    aov_visual = aov_visuals[0]
    aov_projection = aov_visual["visual"]["query"]["queryState"]["Data"]["projections"][0]
    if aov_projection.get("displayName") != "Avg Order M VND":
        fail("AOV card requires a concise, explicit million-VND display label")
    value_properties = aov_visual["visual"].get("objects", {}).get("value", [{}])[0].get("properties", {})
    units = value_properties.get("labelDisplayUnits", {}).get("expr", {}).get("Literal", {}).get("Value")
    precision = value_properties.get("labelPrecision", {}).get("expr", {}).get("Literal", {}).get("Value")
    if (units, precision) != ("1000000D", "2L"):
        fail(f"AOV card must display millions to two decimals, found {(units, precision)}")

    for path in p5.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".tmdl", ".json", ".pbip", ".pbir", ".dax", ".md", ".csv", ".py"}:
            continue
        if path.resolve() == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").casefold()
        if any(token in text for token in ("postgresql://", "postgre://", "postgres_password=", "database_url=")):
            fail(f"credential/connection string found in {path}")
    return len(columns), len(relationship_rows), len(visual_files), workbook_path_status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=PROJECT, help="PBIP file or project directory")
    parser.add_argument("--workbook", type=Path, help="Gold workbook with sibling manifest and table CSVs")
    args = parser.parse_args()
    table_count, relationship_count, visual_count, workbook_path_status = validate(
        project_path=args.project,
        workbook_path=args.workbook,
    )
    print(f"PASS: {table_count} synthetic Gold model tables, {relationship_count} relationships, 3 pages, {visual_count} visuals; workbook/hash, date-table configuration, KPI labels, DAX fields, RLS, inventory exclusion and no-secret checks passed.")
    if workbook_path_status == "unconfigured":
        print("PATH UNCONFIGURED: run dashboards/P5/configure_workbook_path.py before opening or refreshing the PBIP.")
