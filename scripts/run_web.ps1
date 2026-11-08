# Windows version of run_web.sh. Usage: scripts\run_web.ps1 [-Offline]
param([switch]$Offline)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
if ($Offline) { $env:DEMO_OFFLINE = "1"; Write-Host "Offline mode: answering only from saved answers." }
Push-Location web
if (-not (Test-Path node_modules)) { npm ci }
npm run build
Pop-Location
$port = if ($env:PORT) { $env:PORT } else { "8000" }
python -m uvicorn api.main:app --host 127.0.0.1 --port $port
