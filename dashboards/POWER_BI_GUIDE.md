# DataForge Power BI Desktop report

**v1.0-local status: GO LOCAL (P6.2).** The accepted PBIP/PBIR/TMDL source renders three populated pages in Power BI Desktop 2.159.1231.0. P6.2 verified 40 DAX/SQL controls, the `South_Region_Viewer` role, delivery-date measures, local engine refresh and engine-level workbook relocation. The PBIP keeps an unconfigured workbook-path sentinel; configure the regenerated Gold workbook locally before opening or refreshing. No `.pbix` binary or published Power BI Service report is included.

## Run and refresh

From the DataForge workspace root, start the local PostgreSQL pipeline and create the Gold workbook snapshot. Run `generate` only when the existing source folder is absent or its synthetic marker and all recorded hashes are intact; the generator refuses manual, externally sourced, or modified CSV data.

```powershell
.\.venv\Scripts\dataforge.exe generate --orders 3000 --seed 42
.\.venv\Scripts\dataforge.exe ingest
.\.venv\Scripts\dataforge.exe db-init
.\.venv\Scripts\dataforge.exe db-load
.\.venv\Scripts\dataforge.exe db-build
.\.venv\Scripts\dataforge.exe db-check --synthetic
.\.venv\Scripts\python.exe .\scripts\export_powerbi_gold.py --excel
```

Before opening the PBIP, configure its path to the validated local workbook:

```powershell
.\.venv\Scripts\python.exe .\dashboards\P5\configure_workbook_path.py `
  --project .\dashboards\P5\DataForge\DataForge.pbip `
  --workbook .\data\powerbi_gold_export\DataForgeGold.xlsx `
  --backup-dir .\.local\path_backups
.\.venv\Scripts\python.exe .\dashboards\P5\validate_source_pack.py `
  --project .\dashboards\P5\DataForge\DataForge.pbip `
  --workbook .\data\powerbi_gold_export\DataForgeGold.xlsx
```

The configurator verifies that the workbook is synthetic, its SHA-256 matches the sibling `manifest.json`, and sheet names and row counts match before it edits the model. It saves a timestamped copy of `expressions.tmdl` and atomically replaces only `GoldWorkbookPath`. A failed validation leaves the PBIP untouched. `--dry-run` validates without writing.

If the project is moved, copy the complete `data\powerbi_gold_export` folder, including `DataForgeGold.xlsx`, `manifest.json`, and the CSVs, then run the same commands with the moved `.pbip` and workbook paths. Power Query uses the explicitly configured absolute file path; this guide does not claim relative-path resolution. Run the configurator again after moving or recreating the export. Once the validator passes, open `DataForge.pbip` in Power BI Desktop and select **Refresh**.

The workbook contains 11 exported Gold sheets; the report imports 10 and deliberately omits `fct_inventory_snapshot` because it has no geography key and cannot be secured by the regional role. Generated exports are Git-ignored. The PBIP contains no password, PostgreSQL URL or credentials. Refresh remains a local workflow: export the current Gold snapshot, configure/preflight the path, then refresh in Desktop.

The current-source model imports 10 of the 11 exported Gold sheets; inventory is intentionally excluded because it has no geography key. The workbook, manifest and row counts are verified locally. The workbook export is regenerated and ignored by Git; the PBIP path is configurable through the helper above.

## Semantic model

- 10 imported Gold tables, 15 one-to-many relationships, all single-direction.
- `dim_date[date_key]` filters event-date facts. `fct_shipment[ship_date_key]` is the active date role; `delivery_date_key` is inactive and used explicitly by delivery-date measures.
- TMDL marks `dim_date` as the date table on `calendar_date`, which is unique and continuous from 2022-01-01 through 2022-05-20. Auto date/time is disabled, so the model uses the explicit calendar dimension without hidden local date tables.
- Customer history is resolved upstream by SCD2 as-of order date; Power BI relates `dim_customer[customer_key]` to order items.
- Payment, return, shipment, weather and reconciliation facts remain at separate grains. Payment, return and reconciliation facts do not receive product/customer filter paths.

`South_Region_Viewer` applies both `dim_geography[region] = "South"` and `dim_customer[customer_region] = "South"`. In Desktop, use **Modeling → View as → South_Region_Viewer** to test it. The actual role-enforced DAX output was cross-checked against SQL in P6.2. Product master attributes are not region-protected, and inventory is excluded from this model. The role is a portfolio demonstration, not production authorization.

## Report pages

1. **Executive Sales** — fulfilled sales proxy, delivered orders, average order value, gross margin proxy, monthly trend/growth, product category, order-region and customer-segment filters. The banner states that data is synthetic and sales proxy is not recognized revenue.
2. **Finance & Reconciliation** — collected payments, completed refunds, collection variance, split-payment order count, order-level reconciliation details and payment-event drill-down. Event dates are identified separately.
3. **Operations & Weather** — late shipments and P90 by delivery date, eventual return-line rate by product category, rainfall by observation month and province, and source/interpretation notes. Weather association is descriptive, not causal.

## Metric controls

The independent Python `Decimal` oracle and PostgreSQL Gold controls match for fulfilled sales proxy, fulfilled COGS proxy, collected payments, completed refunds and collection variance. Desktop DAX query output also matches the SQL controls for the global model and `South_Region_Viewer`. AOV retains its unrounded division, uses a whole-VND base format, and displays as 1.96M VND on the Executive card. The P6 card label is shortened to **Avg Order (M VND)**; other KPI labels were shortened to fit their card widths without changing measure definitions.

## Screenshots

The linked images below are the genuine current-source P6.2 Desktop captures used for visual acceptance.

- [Executive Sales](../docs/screenshots/v1.0-local/executive_sales_current_source.jpg)
- [Finance & Reconciliation](../docs/screenshots/v1.0-local/finance_reconciliation_current_source.jpg)
- [Operations & Weather](../docs/screenshots/v1.0-local/operations_weather_current_source.jpg)
- See [`docs/releases/v1.0-local.md`](../docs/releases/v1.0-local.md) for the final local acceptance summary and caveats.
