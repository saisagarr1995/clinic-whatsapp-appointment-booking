# Run the clinic fleet on this laptop.
#
#   .\scripts\run_local.ps1
#
# Deliberately does NOT use --reload. The reloader runs a second watcher process
# and roughly doubles memory use for no benefit when you are not editing code.
# For development with auto-restart, pass -Dev.

[CmdletBinding()]
param(
    [switch]$Dev,
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "No virtualenv at .venv. Create it with: py -3.12 -m venv .venv"
}

# Validate every clinic before binding the port, so a broken YAML is reported
# here rather than as a stack trace at startup.
Write-Host "Checking clinic configs..." -ForegroundColor Cyan
& $python scripts\clinic_admin.py check
if ($LASTEXITCODE -ne 0) {
    Write-Error "Fix the clinic config above before starting."
}

if ($Port -eq 0) {
    $Port = 8000
    if (Test-Path .env) {
        $line = Select-String -Path .env -Pattern '^\s*PORT\s*=\s*(\d+)' | Select-Object -First 1
        if ($line) { $Port = [int]$line.Matches[0].Groups[1].Value }
    }
}

Write-Host ""
Write-Host "Fleet starting on http://127.0.0.1:$Port" -ForegroundColor Green
& $python scripts\clinic_admin.py list

$uvicornArgs = @(
    "-m", "uvicorn", "clinic_bot.main:app",
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--workers", "1",          # SQLite + one laptop: more workers would only add RAM
    "--no-access-log"          # keeps the console readable and the log file small
)
if ($Dev) {
    $uvicornArgs = @("-m", "uvicorn", "clinic_bot.main:app",
                     "--host", "127.0.0.1", "--port", "$Port", "--reload")
    Write-Host "DEV MODE: auto-reload on, memory use roughly doubled." -ForegroundColor Yellow
}

& $python @uvicornArgs
