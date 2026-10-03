$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($PSScriptRoot)
& (Join-Path $root "start-training-runtime.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& (Join-Path $root "start-dashboard.ps1")
exit $LASTEXITCODE
