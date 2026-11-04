param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Missing .venv. Create it and install requirements.lock.txt first."
}

Set-Location $root
& $python -m uvicorn app:app --host 127.0.0.1 --port $Port
