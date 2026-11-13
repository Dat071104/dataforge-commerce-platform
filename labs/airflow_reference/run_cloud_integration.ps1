param(
    [string]$ObservationDate
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$adcFile = $env:DATAFORGE_AIRFLOW_ADC_FILE
$callerServiceAccount = $env:DATAFORGE_AIRFLOW_IMPERSONATION_SERVICE_ACCOUNT

if ([string]::IsNullOrWhiteSpace($adcFile) -or -not (Test-Path -LiteralPath $adcFile -PathType Leaf)) {
    throw "Set DATAFORGE_AIRFLOW_ADC_FILE to one explicit keyless ADC file from the isolated DataForge profile."
}
if ($callerServiceAccount -cne "dataforge-week7-airflow@dataforge-p7-lab-d0f725.iam.gserviceaccount.com") {
    throw "Set DATAFORGE_AIRFLOW_IMPERSONATION_SERVICE_ACCOUNT to the approved DataForge Airflow caller service account."
}
$credential = Get-Content -Raw -LiteralPath $adcFile | ConvertFrom-Json
if ($credential.type -eq "service_account") {
    throw "Static service-account key files are not accepted for the Airflow integration run."
}
if ($credential.type -notin @("external_account", "authorized_user")) {
    throw "ADC file must use an external-account or authorized-user source identity, then impersonate the scoped Airflow caller."
}
if (-not [string]::IsNullOrWhiteSpace($ObservationDate) -and
    $ObservationDate -notmatch '^\d{4}-\d{2}-\d{2}$') {
    throw "ObservationDate must use YYYY-MM-DD."
}

$conf = @{ mode = "cloud_integration" }
if (-not [string]::IsNullOrWhiteSpace($ObservationDate)) {
    $conf.observation_date = $ObservationDate
}
$confJson = $conf | ConvertTo-Json -Compress
$escapedConf = $confJson.Replace("'", "'\''")
$logicalDate = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ss+00:00")
$image = "dataforge-airflow-cloud-integration:3.4.0"
$dockerfile = Join-Path $PSScriptRoot "Dockerfile.cloud-integration"
$dagsDirectory = Join-Path $PSScriptRoot "dags"
$resolvedAdc = (Resolve-Path -LiteralPath $adcFile).Path
$containerAdc = "/run/dataforge/credentials/application_default_credentials.json"

Push-Location $repositoryRoot
try {
    & docker build --file $dockerfile --tag $image .
    if ($LASTEXITCODE -ne 0) {
        throw "Could not build the opt-in Airflow integration image."
    }

    $containerCommand = (
        "set -euo pipefail; " +
        "mkdir -p /tmp/airflow; " +
        "airflow db migrate; " +
        "airflow dags test dataforge_week7_weather_cloud '$logicalDate' --conf '$escapedConf'"
    )
    $dockerArguments = @(
        "run", "--rm",
        "--network", "bridge",
        "--user", "50000:0",
        "--env", "AIRFLOW_HOME=/tmp/airflow",
        "--env", "AIRFLOW__CORE__DAGS_FOLDER=/workspace/dags",
        "--env", "AIRFLOW__CORE__LOAD_EXAMPLES=False",
        "--env", "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN=sqlite:////tmp/airflow/airflow.db",
        "--env", "PYTHONPATH=/workspace/dags",
        "--env", "GOOGLE_APPLICATION_CREDENTIALS=$containerAdc",
        "--env", "DATAFORGE_AIRFLOW_IMPERSONATION_SERVICE_ACCOUNT=$callerServiceAccount",
        "--mount", "type=bind,source=$dagsDirectory,target=/workspace/dags,readonly",
        "--mount", "type=bind,source=$resolvedAdc,target=$containerAdc,readonly",
        "--entrypoint", "/bin/bash",
        $image,
        "-lc", $containerCommand
    )
    & docker @dockerArguments
    if ($LASTEXITCODE -ne 0) {
        throw "The Airflow cloud-integration DagRun did not complete successfully."
    }
}
finally {
    Pop-Location
}
