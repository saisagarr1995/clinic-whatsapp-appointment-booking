# Register the clinic fleet as a Windows scheduled task so it starts at logon
# and restarts itself if it crashes. This is the Windows equivalent of the
# systemd unit used on the Oracle VM (PROJECT_PLAN.md D12).
#
#   .\scripts\install_autostart.ps1            install
#   .\scripts\install_autostart.ps1 -Remove    uninstall
#   .\scripts\install_autostart.ps1 -Status    show current state
#
# Deliberately does NOT change your power settings. Sleep is the single biggest
# cause of a dead bot on a laptop, but disabling it affects your whole machine,
# so this script prints the commands and leaves the decision to you.

[CmdletBinding()]
param(
    [switch]$Remove,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
$TaskName = "ClinicWhatsAppBot"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "logs"

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Not installed." -ForegroundColor Yellow
        return
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Task      : $TaskName"
    Write-Host "State     : $($task.State)"
    Write-Host "Last run  : $($info.LastRunTime)"
    Write-Host "Last result: $($info.LastTaskResult)  (0 = ok, 267009 = currently running)"
    Write-Host "Next run  : $($info.NextRunTime)"
}

if ($Status) { Show-Status; return }

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Green
    } else {
        Write-Host "Task '$TaskName' was not installed." -ForegroundColor Yellow
    }
    return
}

if (-not (Test-Path $python)) {
    Write-Error "No virtualenv at .venv — create it before installing autostart."
}
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

# Run through cmd so stdout/stderr can be redirected to a log file the operator
# can actually read after an unattended restart.
$logFile = Join-Path $logDir "fleet.log"
$command = "`"$python`" -m uvicorn clinic_bot.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log >> `"$logFile`" 2>&1"

$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $command" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)   # never kill a long-running server

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Replacing the existing task..." -ForegroundColor Yellow
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Clinic WhatsApp appointment booking fleet" | Out-Null

Write-Host ""
Write-Host "Installed scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "  starts   : at logon"
Write-Host "  restarts : every 1 min on failure, up to 999 times"
Write-Host "  log      : $logFile"
Write-Host ""
Write-Host "Start it now with:  Start-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "-------------------------------------------------------------------" -ForegroundColor Yellow
Write-Host " SLEEP WILL KILL THE BOT. Nothing above prevents that." -ForegroundColor Yellow
Write-Host "-------------------------------------------------------------------" -ForegroundColor Yellow
Write-Host " If patients must be able to book at any hour, run these yourself"
Write-Host " in an ADMIN PowerShell (they change your whole machine, which is"
Write-Host " why this script will not do it for you):"
Write-Host ""
Write-Host "   powercfg /change standby-timeout-ac 0     # never sleep on mains"
Write-Host "   powercfg /change hibernate-timeout-ac 0   # never hibernate"
Write-Host "   powercfg /change monitor-timeout-ac 10    # screen off is fine"
Write-Host ""
Write-Host " Closing the lid still sleeps the laptop by default. To change that:"
Write-Host "   Control Panel > Power Options > Choose what closing the lid does"
Write-Host ""
