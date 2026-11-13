param(
    [ValidateSet("no_new_batch", "local_fixture", "retry_once", "invalid_mode", "scheduler_harness")]
    [string]$Scenario = "no_new_batch"
)

$composeFile = Join-Path $PSScriptRoot "compose.yaml"
$dagId = "dataforge_week7_local_reference"
$logicalDate = "2026-11-11T06:00:00+00:00"

if ($Scenario -eq "no_new_batch") {
    docker compose --file $composeFile run --rm airflow-reference-test
    exit $LASTEXITCODE
}

if ($Scenario -eq "scheduler_harness") {
    $output = docker compose --file $composeFile run --rm airflow-scheduler-harness 2>&1
    $exitCode = $LASTEXITCODE
    $output | Write-Output
    exit $exitCode
}

$conf = switch ($Scenario) {
    "local_fixture" { '{"mode":"local_fixture"}' }
    "retry_once" { '{"mode":"no_new_batch","simulate_transient_once":true}' }
    "invalid_mode" { '{"mode":"not-supported"}' }
}

$escapedConf = $conf.Replace("'", "'\''")
$command = "set -euo pipefail; mkdir -p /tmp/airflow; airflow db migrate; python -m unittest discover -s /workspace/labs/airflow_reference/tests -p 'test_*.py' -v; airflow dags test $dagId $logicalDate --conf '$escapedConf'"
$output = docker compose --file $composeFile run --rm --entrypoint /bin/bash airflow-reference-test -lc $command 2>&1
$exitCode = $LASTEXITCODE
$output | Write-Output

if ($Scenario -eq "invalid_mode") {
    $outputText = $output -join "`n"
    if ($exitCode -eq 0) {
        Write-Error "Invalid mode unexpectedly succeeded; expected AirflowFailException."
        exit 1
    }
    if ($outputText -notmatch "AirflowFailException" -or
        $outputText -notmatch "DATAFORGE_AIRFLOW_FAILURE_ALERT" -or
        $outputText -match "up_for_retry") {
        Write-Error "Non-retryable failure or local alert hook did not match the expected behavior."
        exit 1
    }
    Write-Output "PASS: invalid mode failed without retry and logged the local-only alert hook."
    exit 0
}

if ($exitCode -ne 0) {
    exit $exitCode
}
