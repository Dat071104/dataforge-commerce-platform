param(
    [switch] $Execute
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepositoryRoot
try {
    . .\scripts\enter_dataforge_cloud.ps1 | Out-Null
    $Target = Get-Content -Raw -LiteralPath '.\docs\cloud\target.json' | ConvertFrom-Json
    $ConfiguredProject = gcloud --configuration="$($Target.configuration)" config get-value core/project 2>$null
    if ($LASTEXITCODE -ne 0 -or $ConfiguredProject -ne $Target.project_id) {
        throw 'The active gcloud project does not match the approved DataForge target.'
    }
    if (-not $Execute) {
        & '.\.venv\Scripts\python.exe' '.\scripts\week5_benchmark.py'
        if ($LASTEXITCODE -ne 0) { throw 'The benchmark dry-run failed.' }
        return
    }

    $Token = gcloud --configuration="$($Target.configuration)" auth print-access-token 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $Token) {
        throw 'Could not obtain the short-lived token from the isolated DataForge gcloud session.'
    }
    $env:DATAFORGE_GCP_ACCESS_TOKEN = $Token
    & '.\.venv\Scripts\python.exe' '.\scripts\week5_benchmark.py' --execute
    if ($LASTEXITCODE -ne 0) { throw 'The bounded synthetic BigQuery benchmark failed.' }
}
finally {
    Remove-Item Env:DATAFORGE_GCP_ACCESS_TOKEN -ErrorAction SilentlyContinue
    Remove-Variable Token -ErrorAction SilentlyContinue
    Remove-Item Env:GOOGLE_APPLICATION_CREDENTIALS -ErrorAction SilentlyContinue
    Remove-Item Env:CLOUDSDK_CONFIG -ErrorAction SilentlyContinue
    Remove-Item Env:CLOUDSDK_ACTIVE_CONFIG_NAME -ErrorAction SilentlyContinue
    Remove-Item Env:CLOUDSDK_PYTHON -ErrorAction SilentlyContinue
    Remove-Variable cloudsdk_python -ErrorAction SilentlyContinue
    Pop-Location
}
