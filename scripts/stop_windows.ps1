# Stop and remove the FinAlly container (Windows PowerShell). Idempotent.
# The named volume is preserved so data persists.
$ErrorActionPreference = "Stop"

$Container = "finally"

$existing = docker ps -a --format '{{.Names}}' | Select-String -Pattern "^$Container$"
if ($existing) {
    docker rm -f $Container | Out-Null
    Write-Host "Stopped and removed container '$Container' (data volume preserved)."
} else {
    Write-Host "No container named '$Container' is running."
}
