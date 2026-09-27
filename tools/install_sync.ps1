<#
Shop PC, once: send the shop's data to the bot's server every 30 minutes.

In the car-bot folder, after the setup steps (.venv, requirements-shop.txt, .env):
  powershell -ExecutionPolicy Bypass -File tools\install_sync.ps1

Creates the Windows scheduled task "car-bot sync": at logon and every 30 minutes,
as this Windows user (the one ELYASSER runs as), with no window. It runs
python -m src.sync, which reads ELYASSER (read-only) and uploads the snapshot.
Log: data\sync.log.   Remove it: Unregister-ScheduledTask -TaskName "car-bot sync"
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Host "No .venv in $root - do the setup steps first." -ForegroundColor Red
    Read-Host "Press Enter to close"
    exit 1
}

$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m src.sync" -WorkingDirectory $root
# a daily trigger that repeats every 30 minutes for the whole day: works the same on every Windows version
$often = New-ScheduledTaskTrigger -Daily -At "00:00"
$often.Repetition = (New-ScheduledTaskTrigger -Once -At "00:00" -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$logon = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "car-bot sync" -Action $action -Trigger @($logon, $often) -Settings $settings `
    -Principal $principal -Description "Reads ELYASSER (read-only) and sends the snapshot to the car-bot server" -Force | Out-Null
Start-ScheduledTask -TaskName "car-bot sync"

Write-Host ""
Write-Host "Done: 'car-bot sync' runs at logon and every 30 minutes. First run started now." -ForegroundColor Green
Write-Host "Check in a minute: $root\data\sync.log"
Write-Host ""
Read-Host "Press Enter to close"
