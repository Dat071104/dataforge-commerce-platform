param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]] $Week5Arguments
)

$ErrorActionPreference = 'Stop'
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepositoryRoot
try {
    . .\scripts\enter_dataforge_cloud.ps1
    $Target = Get-Content -Raw -LiteralPath '.\docs\cloud\target.json' | ConvertFrom-Json
    $ConfiguredProject = gcloud --configuration="$($Target.configuration)" config get-value core/project 2>$null
    if ($LASTEXITCODE -ne 0 -or $ConfiguredProject -ne $Target.project_id) {
        throw 'The active gcloud project does not match the approved DataForge target.'
    }

    $Python = Join-Path $RepositoryRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw 'The repository Python 3.11 virtual environment is missing.'
    }
    if (-not $Week5Arguments -or $Week5Arguments.Count -eq 0) {
        throw 'Pass a Week-5 subcommand, for example: batch --max-events 1000.'
    }

    $NeedsCloudAuth = $false
    if ($Week5Arguments[0] -in @('status', 'job-stats', 'record-failed-attempt', 'reconcile')) {
        $NeedsCloudAuth = $true
    }
    if ($Week5Arguments[0] -eq 'schema' -and $Week5Arguments -contains '--execute') {
        $NeedsCloudAuth = $true
    }
    if ($Week5Arguments[0] -eq 'batch' -and $Week5Arguments -contains '--execute') {
        $NeedsCloudAuth = $true
    }

    if ($NeedsCloudAuth) {
        # gcloud emits a one-line active-configuration notice to stderr on
        # first use; keep that informational text from becoming a terminating
        # PowerShell NativeCommandError under Stop semantics.
        $Token = gcloud --configuration="$($Target.configuration)" auth print-access-token 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $Token) {
            throw 'Could not obtain a short-lived token from the active isolated gcloud identity.'
        }
        $env:DATAFORGE_GCP_ACCESS_TOKEN = $Token
    }

    & $Python '.\scripts\week5_incremental.py' @Week5Arguments
    if ($LASTEXITCODE -ne 0) { throw 'The Week-5 command failed.' }
}
finally {
    Remove-Item Env:DATAFORGE_GCP_ACCESS_TOKEN -ErrorAction SilentlyContinue
    Remove-Variable Token -ErrorAction SilentlyContinue
    Pop-Location
}
