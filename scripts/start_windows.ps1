# Start the FinAlly container (Windows PowerShell). Idempotent.
# Usage: .\scripts\start_windows.ps1 [-Build]
param([switch]$Build)

$ErrorActionPreference = "Stop"

$Image     = "finally"
$Container = "finally"
$Volume    = "finally-data"
$Port      = "8000"

$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

if (-not (Test-Path ".env")) {
    Write-Error "`.env not found in $RootDir. Copy the template first: copy .env.example .env  (then add your API key)"
    exit 1
}

$imageExists = docker image inspect $Image 2>$null
if ($Build -or -not $imageExists) {
    Write-Host "Building image '$Image'..."
    docker build -t $Image .
}

$existing = docker ps -a --format '{{.Names}}' | Select-String -Pattern "^$Container$"
if ($existing) {
    docker rm -f $Container | Out-Null
}

docker run -d `
    --name $Container `
    -p "${Port}:8000" `
    -v "${Volume}:/app/db" `
    --env-file .env `
    $Image | Out-Null

Write-Host "FinAlly is starting at http://localhost:$Port"
