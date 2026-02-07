@echo off
setlocal
cd /d "%~dp0"
if not exist "reports\vitest\index.html" (
  echo Report not found. Run: npm run test:report
  exit /b 1
)
start "" /b npx vite preview --outDir reports/vitest --port 4173
timeout /t 2 /nobreak >nul
start "" "http://localhost:4173"
