param(
    [switch]$StopAfter
)

$ErrorActionPreference = "Stop"
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI is not on PATH. Start Docker Desktop, reopen PowerShell, and retry."
}

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
docker compose up --build --detach

$healthy = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try {
        $health = Invoke-RestMethod http://127.0.0.1:8000/api/health -TimeoutSec 3
        if ($health.status -eq "ok") {
            $healthy = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if (-not $healthy) {
    docker compose logs trendsmapp
    throw "Container did not become healthy within 60 seconds."
}

docker compose ps
Write-Host "Trendsmapp is healthy at http://127.0.0.1:8000"
if ($StopAfter) {
    docker compose down
}
