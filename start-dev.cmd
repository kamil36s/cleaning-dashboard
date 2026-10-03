@echo off
setlocal
cd /d "%~dp0"
set "FORCE_COLOR=1"
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"

where node >nul 2>&1
if errorlevel 1 (
  call :sys "Node.js was not found in PATH."
  exit /b 1
)

node "%ROOT%\scripts\dev-banner.js"

if not defined SKIP_TRAINING_RUNTIME (
  call :sys "Ensuring the independent Training Runtime is ready..."
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\start-training-runtime.ps1"
  if errorlevel 1 exit /b 1
  echo.
)

call :sys "Checking old project services and required ports..."
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\stop-dev-services.ps1" -Root "%ROOT%" -Service All
if errorlevel 1 (
  call :sys "Nothing new was started. Resolve the port conflict and try again."
  exit /b 1
)
echo.

call :sys "Ensuring optional Kermit service is ready..."
node "%ROOT%\scripts\kermit-autostart.js"
if errorlevel 1 call :sys "Kermit is unavailable; continuing dashboard startup."
echo.

call :sys "Starting API, Network Monitor and Mi Scale in background..."
start /B "" node "%ROOT%\scripts\dev-service.js" api
start /B "" node "%ROOT%\scripts\dev-service.js" network
start /B "" node "%ROOT%\scripts\dev-service.js" scale

call :sys "Waiting for API and Network Monitor readiness..."
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\wait-dev-services.ps1" -TimeoutSeconds 30
if errorlevel 1 (
  call :sys "Backend startup failed. Cleaning up partial services..."
  powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\stop-dev-services.ps1" -Root "%ROOT%" -Service All
  exit /b 1
)

call :sys "Starting Vite in the foreground. The stack stops when Vite exits."
node "%ROOT%\scripts\dev-service.js" vite
set "VITE_EXIT=%ERRORLEVEL%"

echo.
call :sys "Vite stopped. Cleaning up this project's remaining services..."
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\stop-dev-services.ps1" -Root "%ROOT%" -Service All
exit /b %VITE_EXIT%

:sys
set "NOW=%time: =0%"
echo %NOW:~0,8% [SYS]   ^| %~1
exit /b 0
