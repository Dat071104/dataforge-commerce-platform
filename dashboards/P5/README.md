# DataForge Power BI source pack

This is a local, synthetic-only PBIP/PBIR/TMDL project. The **v1.0-local P6.2 result is GO LOCAL**: the controlled PBIR source passed structural validation and all three pages were rendered in Power BI Desktop. The model imports a generated Gold workbook through a configurable `GoldWorkbookPath` sentinel. No `.pbix`, credentials, PostgreSQL connection string or published Power BI Service report is included.

## Input and refresh

The model imports ten sheets from the eleven-sheet Gold export. The PBIP source ships with a local workbook-path sentinel; configure the path before opening or refreshing the report.

Generate the workbook and CSV snapshots with:

```powershell
.\.venv\Scripts\python.exe .\scripts\export_powerbi_gold.py --excel
```

Before opening the report, validate and configure the workbook path:

```powershell
.\.venv\Scripts\python.exe .\dashboards\P5\configure_workbook_path.py `
  --project .\dashboards\P5\DataForge\DataForge.pbip `
  --workbook .\data\powerbi_gold_export\DataForgeGold.xlsx
.\.venv\Scripts\python.exe .\dashboards\P5\validate_source_pack.py `
  --project .\dashboards\P5\DataForge\DataForge.pbip `
  --workbook .\data\powerbi_gold_export\DataForgeGold.xlsx
```

The configurator checks the synthetic marker, workbook SHA-256, sheet names and row counts against the sibling `manifest.json`, then saves a timestamped TMDL backup and atomically updates only `GoldWorkbookPath`. A failed validation leaves the project unchanged. On relocation, copy the full Gold export folder and pass the new workbook path; Power Query uses the configured absolute path, so no relative-path behavior is assumed. No password or database credential is stored in the project.

`fct_inventory_snapshot` is intentionally **not imported**. It has no geography key and cannot be correctly filtered by the regional RLS role.

## Open and validate

After configuring the workbook path, open `DataForge/DataForge.pbip` in Power BI Desktop. The project contains `Executive Sales`, `Finance & Reconciliation`, and `Operations & Weather` PBIR pages; model definitions and the RLS role are in the TMDL semantic model folder. The accepted gross margin label is `Gross Margin Proxy (VND)`; its formula remains fulfilled sales proxy less fulfilled COGS proxy. Use `RELATIONSHIPS.csv`, `DAX_MEASURES.dax`, and `REPORT_PAGE_SPEC.md` as review inventories.

The PBIR package uses report content version `2.0.0`, `ReportSection`-prefixed page IDs, a registered local theme resource and the companion `.platform` metadata. If Desktop still opens only a blank `Page 1`, save a minimal PBIR project from that Desktop build and compare its generated page/report metadata before changing this package. This project does not use PBIR-Legacy `report.json` content.

The `South_Region_Viewer` role filters both `dim_geography[region] = "South"` and `dim_customer[customer_region] = "South"`. It is a model-level demonstration, not production authorization. Product master rows are not region-protected. Inventory is absent from the model and every page.

The Executive Sales page has date, order-region and customer-segment slicers; customer-segment filtering reaches order-item measures through the SCD2 customer surrogate relationship.

The model disables automatic date/time and marks `dim_date[calendar_date]` as the unique date key, avoiding hidden local date tables.

Date roles are explicit: fulfilled sales and collection variance use order date; payments use payment date; refunds use return date; the active shipment relationship uses ship date, while late/P90 measures activate delivery date; weather uses observation date. The Return Line Rate uses an order-date cohort of delivered item IDs, then counts any associated completed return events after removing the return-date filter. It is a line rate, not a unit-return rate. Weather visuals are province-level and non-causal. Fulfilled sales is a proxy, not recognized revenue.

Average Order Value retains an unrounded `DIVIDE` calculation and a whole-VND base formatString (`#,##0`). The Executive card explicitly overrides visual display units to Millions with two decimals, so the current SQL value `1,961,999.0249609984` and Query View value `1,961,999.0250000000` both appear as `1.96M` VND. No epsilon or artificial adjustment is applied.

TMDL carries the date-table metadata; `dim_date[calendar_date]` is unique and continuous from 2022-01-01 through 2022-05-20 in this fixture.

## v1.0-local verification

- P6.2: **GO LOCAL** after one independent controller review. The current-source copy passed source-pack and layout bounds/overlap checks (10 model tables, 15 relationships, 3 pages, 33 visuals).
- Forty DAX/SQL comparison checks passed, including South_Region_Viewer and delivery-date controls. The South role was applied in the semantic model, not simulated with a page filter.
- Full local Desktop engine refresh and workbook relocation refresh passed. The final Operations visual geometry was loaded and captured; the `Weather Source` caption is fully visible.
- The last layout edit changed PBIR visual geometry only. Numeric DAX, M partitions, relationships and RLS filters remain unchanged. The 40 controls were not rerun after that visual-only edit.
- Three current-source Desktop screenshots are included: [Executive Sales](../../docs/screenshots/v1.0-local/executive_sales_current_source.jpg), [Finance & Reconciliation](../../docs/screenshots/v1.0-local/finance_reconciliation_current_source.jpg), and [Operations & Weather](../../docs/screenshots/v1.0-local/operations_weather_current_source.jpg). Chart axis/category labels are small at Page Fit but visible. Official PBIR schema validation and a Desktop UI reopen from the relocated PBIP remain unverified.

The source-pack validator verifies workbook hashes/row counts, TMDL date settings, KPI labels, model references, RLS filters, page structure, AOV formatting and absence of embedded credentials. Concise release evidence is in [`../../docs/releases/v1.0-local.md`](../../docs/releases/v1.0-local.md); older phase-by-phase logs remain local and are not required to reproduce this PBIP.
