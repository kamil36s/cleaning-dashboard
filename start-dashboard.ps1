$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$env:SKIP_TRAINING_RUNTIME = "1"
& $env:ComSpec /d /c (Join-Path $root "start-dev.cmd")
exit $LASTEXITCODE
