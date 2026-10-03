@echo off
setlocal
cd /d "%~dp0"

if not defined IDLE_MINUTES set "IDLE_MINUTES=3"
if not defined CHECK_INTERVAL_MS set "CHECK_INTERVAL_MS=5000"
if not defined DASHBOARD_URL set "DASHBOARD_URL=http://127.0.0.1:8000"
if not defined CHROME_PROFILE_DIR set "CHROME_PROFILE_DIR=%~dp0.chrome-spotify-screensaver"

set "AHK_EXE=%ProgramFiles%\AutoHotkey\v2\AutoHotkey64.exe"
if exist "%AHK_EXE%" (
  start "" "%AHK_EXE%" "%~dp0spotify-screensaver.ahk"
  exit /b 0
)

start "" "%~dp0spotify-screensaver.ahk"
