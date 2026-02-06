@echo off
setlocal
cd /d "%~dp0.."
python scripts\build-habits.py
if errorlevel 1 (
  echo.
  echo Import failed. Press any key to close.
  pause >nul
  exit /b 1
)
echo.
echo Import complete. Press any key to close.
pause >nul
