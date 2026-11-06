$ErrorActionPreference = 'Stop'
if (!(Test-Path .env)) { Copy-Item .env.example .env; Write-Host 'Edit .env and change local password.' }
py -3.11 -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Python 3.11 venv creation failed with exit code $LASTEXITCODE" }
./.venv/Scripts/python.exe -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed with exit code $LASTEXITCODE" }
./.venv/Scripts/python.exe -m pip install -c requirements-py311.lock -e ".[dev,powerbi]"
if ($LASTEXITCODE -ne 0) { throw "locked project installation failed with exit code $LASTEXITCODE" }
Write-Host 'Bootstrap complete. Next: docker compose up -d --wait'
