@echo off
REM ApplyPilot daily apply — invoked by Windows Task Scheduler at 08:00 local.
wsl.exe -d Ubuntu -e bash /mnt/c/Users/elihe/Projects/applypilot/scripts/daily_apply.sh
exit /b %ERRORLEVEL%
