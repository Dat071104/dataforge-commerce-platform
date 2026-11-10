param(
    [Parameter(Mandatory = $true)]
    [string] $ManifestUri,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [long]::MaxValue)]
    [long] $ManifestGeneration,
    [Parameter(Mandatory = $true)]
    [ValidateSet('normal', 'backfill')]
    [string] $RunMode,
    [ValidateSet('', 'after_stage', 'before_merge', 'before_publish')]
    [string] $FailAt = '',
    [switch] $FailAfterMergeOnce,
    [switch] $ProbeStorageCreateDenied
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
    $ExpectedManifestPrefix = "gs://$($Target.bucket)/manifests/week5/"
    if (-not $ManifestUri.StartsWith($ExpectedManifestPrefix, [StringComparison]::Ordinal)) {
        throw 'Manifest URI must use the approved bucket and Week-5 manifest prefix.'
    }

    $ContainerArgs = @(
        "--manifest-uri=$ManifestUri",
        "--manifest-generation=$ManifestGeneration",
        "--run-mode=$RunMode"
    )
    if ($FailAfterMergeOnce) { $ContainerArgs += '--fail-after-merge-once' }
    if ($ProbeStorageCreateDenied) { $ContainerArgs += '--probe-storage-create-denied' }
    if ($FailAt) { $ContainerArgs += "--fail-at=$FailAt" }
    $ArgsValue = $ContainerArgs -join ','
    $GcloudArgs = @(
        'run', 'jobs', 'execute', 'dataforge-week5-processor',
        "--project=$($Target.project_id)",
        "--region=$($Target.region)",
        "--args=$ArgsValue",
        '--tasks=1',
        '--task-timeout=600s',
        '--wait'
    )
    # Preserve gcloud's progress/error text while keeping native stderr from
    # short-circuiting the exit-code check under PowerShell Stop semantics.
    gcloud --configuration="$($Target.configuration)" @GcloudArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw 'Cloud Run execution failed. Retain the execution ID and inspect its bounded logs before recovery.'
    }
}
finally {
    Pop-Location
}
