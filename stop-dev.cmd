@echo off
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\scripts\stop-dev-services.ps1" -Root "%ROOT%" -Service All
exit /b %ERRORLEVEL%
