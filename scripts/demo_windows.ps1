$ErrorActionPreference = 'Stop'
$df = '.\.venv\Scripts\dataforge.exe'

function Invoke-DataForge {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & $df @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "dataforge $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Invoke-ProjectPython {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & .\.venv\Scripts\python.exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python check $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

Invoke-DataForge @('generate', '--orders', '3000', '--seed', '42')
Invoke-DataForge @('ingest')
Invoke-DataForge @('db-init')
Invoke-DataForge @('db-load')
Invoke-DataForge @('db-build')

$checks = & $df db-check --synthetic | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "db-check failed with exit code $LASTEXITCODE" }
$failedChecks = @($checks.PSObject.Properties | Where-Object { [decimal]$_.Value -ne 0 })
if ($failedChecks.Count -gt 0) {
    throw "Synthetic database checks are nonzero: $($failedChecks.Name -join ', ')"
}

$metrics = & $df reference-metrics | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "reference-metrics failed with exit code $LASTEXITCODE" }
$expectedMetrics = @{
    fulfilled_sales_proxy_vnd = '5030565500.00'
    fulfilled_cogs_proxy_vnd = '2946637500'
    collected_vnd = '5030565500'
    completed_refunds_vnd = '135428000'
    collection_variance_vnd = '0.00'
}
foreach ($name in $expectedMetrics.Keys) {
    if ([decimal]$metrics.$name -ne [decimal]$expectedMetrics[$name]) {
        throw "Financial control $name did not match the seed-42 oracle"
    }
}
Invoke-ProjectPython @('.\scripts\verify_financial_controls.py')

Get-ChildItem .\sql\analysis\q*.sql | Sort-Object Name | ForEach-Object {
    Invoke-DataForge @('query', $_.BaseName)
}

Write-Host 'Repeat ingest/load/build to verify idempotent source reruns.'
Invoke-DataForge @('ingest')
Invoke-DataForge @('db-load')
Invoke-DataForge @('db-build')
$repeatChecks = & $df db-check --synthetic | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "repeat db-check failed with exit code $LASTEXITCODE" }
$repeatFailures = @($repeatChecks.PSObject.Properties | Where-Object { [decimal]$_.Value -ne 0 })
if ($repeatFailures.Count -gt 0) {
    throw "Repeat synthetic database checks are nonzero: $($repeatFailures.Name -join ', ')"
}
Invoke-ProjectPython @('.\scripts\verify_financial_controls.py')
Write-Host 'Synthetic CSV → Parquet → PostgreSQL → Gold → ten analyses passed; financial controls match seed 42.'
