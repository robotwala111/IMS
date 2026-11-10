# Run this script from anywhere to start the backend server correctly.
# Usage: .\run.ps1
# Optional: .\run.ps1 --port 9000

param(
    [string]$bindHost = "0.0.0.0",
    [int]$port = 8000,
    [switch]$no_reload
)

$backendDir = "$PSScriptRoot"
$python = "$backendDir\venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Backend venv not found at: $python"
    Write-Host "Run this first: python -m venv venv && .\venv\Scripts\Activate.ps1 && pip install -r requirements.txt"
    exit 1
}

Set-Location $backendDir

$reloadFlag = if ($no_reload) { "" } else { "--reload" }

Write-Host ""
Write-Host "Starting ScienceTech-IMS backend..." -ForegroundColor Cyan
Write-Host "Python : $python" -ForegroundColor DarkGray
Write-Host "URL    : http://$bindHost`:$port" -ForegroundColor Green
Write-Host "Docs   : http://localhost:$port/api/v1/docs" -ForegroundColor Green
Write-Host ""

& $python -m uvicorn app.main:app $reloadFlag --host $bindHost --port $port
