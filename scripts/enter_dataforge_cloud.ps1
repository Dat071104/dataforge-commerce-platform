# Dot-source this file to configure only the current PowerShell session:
# . D:\DATA_ENGINEER\DataForge\scripts\enter_dataforge_cloud.ps1
# Keep credentials outside AppData: Microsoft Store Python redirects that path.

$DataForgeTargetFile = Join-Path $PSScriptRoot '..\docs\cloud\target.json'
$DataForgeTarget = Get-Content -Raw -LiteralPath $DataForgeTargetFile -ErrorAction Stop | ConvertFrom-Json
$DataForgeGcloudRoot = Join-Path (Join-Path $env:USERPROFILE '.config') $DataForgeTarget.sdk_directory
$DataForgeGcloudConfiguration = $DataForgeTarget.configuration
$DataForgeGcloudConfigFile = Join-Path $DataForgeGcloudRoot (
    'configurations\config_' + $DataForgeGcloudConfiguration
)
$DataForgeAdcFile = Join-Path $DataForgeGcloudRoot 'application_default_credentials.json'

if (-not (Test-Path -LiteralPath $DataForgeGcloudConfigFile -PathType Leaf)) {
    throw "DataForge configuration is missing from $DataForgeGcloudRoot"
}
if (-not (Test-Path -LiteralPath $DataForgeAdcFile -PathType Leaf)) {
    throw "DataForge ADC is missing from $DataForgeGcloudRoot"
}

$DataForgeGcloudLauncher = Get-Command gcloud.ps1 -ErrorAction Stop
$DataForgeSdkRoot = Split-Path -Parent (Split-Path -Parent $DataForgeGcloudLauncher.Source)
$DataForgeSdkPython = Join-Path $DataForgeSdkRoot 'platform\bundledpython\python.exe'
if (-not (Test-Path -LiteralPath $DataForgeSdkPython -PathType Leaf)) {
    throw 'The Google Cloud SDK bundled Python interpreter was not found.'
}

$env:CLOUDSDK_CONFIG = $DataForgeGcloudRoot
$env:CLOUDSDK_ACTIVE_CONFIG_NAME = $DataForgeGcloudConfiguration
$env:CLOUDSDK_PYTHON = $DataForgeSdkPython
$env:GOOGLE_APPLICATION_CREDENTIALS = $DataForgeAdcFile
# gcloud.ps1 checks this PowerShell variable before CLOUDSDK_PYTHON.
$cloudsdk_python = $DataForgeSdkPython

Write-Output "DataForge cloud session: $DataForgeGcloudConfiguration"
Write-Output "Credential directory: $DataForgeGcloudRoot"
