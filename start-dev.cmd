@echo off
setlocal
cd /d "%~dp0"

echo ------------------------------------------------------------
echo Cleaning Dashboard - Dev Mode
echo ------------------------------------------------------------
echo This starts two things in ONE window:
echo 1) Local SQLite API  - http://127.0.0.1:8000
echo 2) Vite Dev Server   - http://localhost:5173/cleaning-dashboard/
echo.
echo Close this window to stop both.
echo ------------------------------------------------------------
echo.

echo Stopping any old API/Vite (ports 8000/5173)...
set "ROOT=%~dp0"
powershell -NoProfile -Command ^
  "$root = '%ROOT%'.TrimEnd('\');" ^
  "$rootEsc = [regex]::Escape($root);" ^
  "$ErrorActionPreference='SilentlyContinue';" ^
  "Get-NetTCPConnection -LocalPort 8000,5173 -State Listen | Select-Object -Unique OwningProcess | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force };" ^
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $rootEsc -and $_.CommandLine -match 'server\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force };" ^
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match $rootEsc -and $_.CommandLine -match 'vite' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo.

echo Starting API (SQLite) in background...
start /B "" cmd /c "py server.py || python server.py"

echo Starting Vite (frontend)...
npm run dev
