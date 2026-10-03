param(
    [int]$Port = 8766,
    [int]$TimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$probeUrl = "http://127.0.0.1:$Port/api/live-workout/health"

function Test-TrainingRuntime {
    try {
        $response = Invoke-RestMethod -Uri $probeUrl -TimeoutSec 2
        return $response.ok -eq $true -and $response.service -eq "training-runtime"
    } catch {
        return $false
    }
}

if (Test-TrainingRuntime) {
    Write-Host "Training Runtime is already ready on port $Port."
    exit 0
}

if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $Port is occupied by a different process. Training Runtime was not started."
}

$python = Get-Command py -ErrorAction SilentlyContinue
$arguments = @("-3", "-u", (Join-Path $root "training_runtime.py"))
if (-not $python) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    $arguments = @("-u", (Join-Path $root "training_runtime.py"))
}
if (-not $python) {
    throw "Python was not found in PATH."
}

$env:TRAINING_RUNTIME_PORT = [string]$Port
$process = Start-Process `
    -FilePath $python.Source `
    -ArgumentList $arguments `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $root "training-runtime.log") `
    -RedirectStandardError (Join-Path $root "training-runtime-error.log") `
    -PassThru

$deadline = (Get-Date).AddSeconds([Math]::Max(2, $TimeoutSeconds))
while ((Get-Date) -lt $deadline) {
    if (Test-TrainingRuntime) {
        Write-Host "Training Runtime ready on port $Port (PID $($process.Id))."
        exit 0
    }
    if ($process.HasExited) {
        throw "Training Runtime exited during startup (code $($process.ExitCode)). Check training-runtime-error.log."
    }
    Start-Sleep -Milliseconds 200
}

throw "Training Runtime did not become ready within $TimeoutSeconds seconds."
