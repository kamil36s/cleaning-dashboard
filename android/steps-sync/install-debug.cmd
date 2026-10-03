@echo off
setlocal
cd /d "%~dp0"
set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
if not exist "%ADB%" (
  echo adb.exe not found at %ADB%
  exit /b 1
)
"%ADB%" devices
"%ADB%" install -r "app\build\outputs\apk\debug\app-debug.apk"
