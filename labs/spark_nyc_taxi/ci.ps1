param()

$ErrorActionPreference = 'Stop'
$ComposeFile = Join-Path $PSScriptRoot 'compose.yaml'
$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Push-Location $RepositoryRoot
try {
    docker compose --file $ComposeFile build
    if ($LASTEXITCODE -ne 0) { throw "Spark lab image build failed: $LASTEXITCODE" }

    docker compose --file $ComposeFile run --rm spark `
        -m pytest -q labs/spark_nyc_taxi/tests
    if ($LASTEXITCODE -ne 0) { throw "Spark lab fixture suite failed: $LASTEXITCODE" }
}
finally {
    Pop-Location
}
