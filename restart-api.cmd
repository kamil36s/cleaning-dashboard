@echo off
setlocal
cd /d "%~dp0"

call :sys "Restarting local dashboard API on port 8000..."
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "API_LOG_DIR=%ROOT%\data\logs"
where node >nul 2>&1
if errorlevel 1 (
  call :sys "Node.js was not found in PATH."
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\stop-dev-services.ps1" -Root "%ROOT%" -Service Api
if errorlevel 1 exit /b 1

call :sys "Starting API..."
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$logDir = '%API_LOG_DIR%'; $script = Join-Path '%ROOT%' 'scripts\dev-service.js'; $arguments = '"' + $script + '" api'; New-Item -ItemType Directory -Path $logDir -Force | Out-Null; $process = Start-Process -FilePath 'node' -ArgumentList $arguments -WorkingDirectory '%ROOT%' -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDir 'api-watchdog.out.log') -RedirectStandardError (Join-Path $logDir 'api-watchdog.err.log') -PassThru; if (-not $process) { exit 1 }"
if errorlevel 1 (
  call :sys "Could not launch the API watchdog."
  exit /b 1
)
powershell -NoProfile -Command "$limit=(Get-Date).AddSeconds(20); do { if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 0 }; Start-Sleep -Milliseconds 250 } while ((Get-Date) -lt $limit); exit 1"
if errorlevel 1 (
  call :sys "API did not become ready within 20 seconds. Check the [API] error above."
  exit /b 1
)
call :sys "API ready at http://127.0.0.1:8000"
exit /b 0

:sys
set "NOW=%time: =0%"
echo %NOW:~0,8% [SYS]   ^| %~1
exit /b 0
