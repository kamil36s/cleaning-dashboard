@echo off
setlocal
cd /d "%~dp0"

if not defined PORT set "PORT=4173"
if not defined DASHBOARD_URL set "DASHBOARD_URL=http://localhost:%PORT%"

echo Starting dashboard on %DASHBOARD_URL% ...
start "Cleaning Dashboard" cmd /k "cd /d ""%~dp0"" && npm run start:dashboard"

echo Waiting for the dashboard to start...
timeout /t 5 /nobreak >nul

echo Starting Spotify screensaver watcher...
call "%~dp0start-spotify-screensaver-watcher.bat"
