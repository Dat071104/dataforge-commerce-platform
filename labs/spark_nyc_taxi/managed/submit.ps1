param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9-]{4,28}[a-z0-9]$')]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z]+-[a-z]+[0-9]$')]
    [string]$Region,

    [Parameter(Mandatory = $true)]
    [ValidateSet(1, 2)]
    [int]$AttemptNumber,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$ServiceAccount,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$RuntimeVersion,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^gs://[a-z0-9._-]+/?$')]
    [string]$StagingBucket,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^gs://[^/]+/.+\.py$')]
    [string]$MainPythonUri,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^gs://[^/]+/.+\.zip$')]
    [string]$PyFilesUri,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^gs://[^/]+/.+\.parquet$')]
    [string]$TripUri,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^gs://[^/]+/.+\.csv$')]
    [string]$ZonesUri,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^gs://[^/]+/.+\.json$')]
    [string]$SourceManifestUri,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^gs://[^/]+/.+\.json$')]
    [string]$LocalOracleUri,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^gs://[^/]+/tlc_managed/2024-01/[^/]+$')]
    [string]$OutputUri,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$SourceSha256,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{64}$')]
    [string]$ZoneSha256,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ $_ -gt 0 })]
    [long]$SourceGeneration,

    [Parameter(Mandatory = $true)]
    [ValidateScript({ $_ -gt 0 })]
    [long]$ZoneGeneration,

    [Parameter(Mandatory = $true)]
    [ValidateRange(0, 1000000)]
    [double]$MaximumShuffleGiB,

    [Parameter(Mandatory = $true)]
    [ValidateRange(0, 1000000)]
    [double]$OtherServicesUpperBoundUsd,

    [switch]$Submit
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$Preflight = Join-Path $PSScriptRoot 'preflight.py'
$BatchId = "dataforge-w6-tlc-2024-01-a$AttemptNumber"

$preflightJson = & python $Preflight `
    --dcus 12 `
    --ttl-minutes 30 `
    --attempts 2 `
    --max-shuffle-gib $MaximumShuffleGiB `
    --other-services-upper-bound-usd $OtherServicesUpperBoundUsd
$preflightExitCode = $LASTEXITCODE
if ($preflightExitCode -ne 0) {
    throw "C7 gross cost preflight blocked submission (exit $preflightExitCode)."
}
$preflight = $preflightJson | ConvertFrom-Json
if (-not $preflight.submit_allowed) {
    throw "C7 gross cost preflight returned $($preflight.status); no batch was submitted."
}

$plan = [pscustomobject]@{
    project_id         = $ProjectId
    region             = $Region
    batch_id           = $BatchId
    attempt            = $AttemptNumber
    ttl                = '30m'
    retries            = 0
    runtime_version    = $RuntimeVersion
    source_sha256      = $SourceSha256
    source_generation  = $SourceGeneration
    estimated_cost_usd = $preflight.total_usd
    cost_status        = $preflight.status
    output_uri         = $OutputUri
}

if (-not $Submit) {
    $plan | ConvertTo-Json -Compress
    return
}

# Only the explicit -Submit path authenticates and calls Dataproc. This script
# was not invoked with -Submit during Phase 2.
. (Join-Path $RepoRoot 'scripts\enter_dataforge_cloud.ps1')
$activeProject = (& gcloud config get-value project 2>$null).Trim()
if ($activeProject -ne $ProjectId) {
    throw "Isolated gcloud project '$activeProject' does not match explicit '$ProjectId'."
}
$observedGeneration = (& gcloud storage objects describe $TripUri --project $ProjectId --format='value(generation)').Trim()
if ($LASTEXITCODE -ne 0 -or $observedGeneration -ne "$SourceGeneration") {
    throw "Read-only source generation check failed: expected $SourceGeneration, observed $observedGeneration."
}
$observedZoneGeneration = (& gcloud storage objects describe $ZonesUri --project $ProjectId --format='value(generation)').Trim()
if ($LASTEXITCODE -ne 0 -or $observedZoneGeneration -ne "$ZoneGeneration") {
    throw "Read-only zone generation check failed: expected $ZoneGeneration, observed $observedZoneGeneration."
}

$sparkProperties = @(
    'spark.dynamicAllocation.enabled=false',
    'spark.executor.instances=2',
    'spark.executor.cores=4',
    'spark.executor.memory=16g',
    'spark.driver.cores=4',
    'spark.driver.memory=16g',
    'spark.task.maxFailures=1',
    'spark.stage.maxConsecutiveAttempts=1'
) -join ','
$driverArgs = @(
    '--batch-id', $BatchId,
    '--trip-uri', $TripUri,
    '--zones-uri', $ZonesUri,
    '--source-manifest-uri', $SourceManifestUri,
    '--source-sha256', $SourceSha256,
    '--zone-sha256', $ZoneSha256,
    '--source-generation', "$SourceGeneration",
    '--zone-generation', "$ZoneGeneration",
    '--local-oracle-uri', $LocalOracleUri,
    '--output-uri', $OutputUri
)

& gcloud dataproc batches submit pyspark $MainPythonUri `
    --project $ProjectId `
    --region $Region `
    --batch $BatchId `
    --ttl 30m `
    --version $RuntimeVersion `
    --service-account $ServiceAccount `
    --staging-bucket $StagingBucket `
    --py-files $PyFilesUri `
    --properties $sparkProperties `
    --labels application=dataforge,phase=week6 `
    --user-workload-authentication-type SERVICE_ACCOUNT `
    -- $driverArgs
if ($LASTEXITCODE -ne 0) {
    throw "Dataproc Serverless submit failed with exit code $LASTEXITCODE; no automatic retry is configured."
}
$plan | ConvertTo-Json -Compress
