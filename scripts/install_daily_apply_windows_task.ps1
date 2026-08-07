# Register Windows Task Scheduler job for ApplyPilot daily apply at 08:00 local time.
# Prefer this over WSL-only cron: Windows wakes WSL at 8am even if the VM was idle.
$ErrorActionPreference = "Stop"

$TaskName = "ApplyPilot Daily Apply"
$Cmd = "C:\Users\elihe\Projects\applypilot\scripts\run_daily_apply.cmd"

if (-not (Test-Path $Cmd)) {
    throw "Missing wrapper: $Cmd"
}

schtasks /Create /TN $TaskName /SC DAILY /ST 08:00 /RL LIMITED /F /TR $Cmd | Out-Host
schtasks /Create /TN "ApplyPilot Keep WSL Awake" /SC HOURLY /F /TR "wsl.exe -d Ubuntu -e true" | Out-Host

Write-Host ""
Write-Host "Registered:"
schtasks /Query /TN $TaskName /V /FO LIST | Select-String -Pattern "TaskName|Next Run|Last Run|Last Result|Status|Task To Run|Start Time|Schedule Type"
Write-Host ""
Write-Host "Note: .wslconfig vmIdleTimeout=-1 needs a one-time 'wsl --shutdown' then reopen WSL."
Write-Host "Test now: $Cmd"
