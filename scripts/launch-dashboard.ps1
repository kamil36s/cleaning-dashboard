param(
    [string]$DashboardUrl = "http://localhost:5173/cleaning-dashboard/",
    [string]$BackendProbeUrl = "http://127.0.0.1:8000/api/ai-usage",
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$startScript = Join-Path $root "start-dev.cmd"
$trainingScript = Join-Path $root "start-training-runtime.ps1"

function Test-DashboardReady {
    $uri = [Uri]$DashboardUrl
    $frontendReady = [bool](Get-NetTCPConnection -LocalPort $uri.Port -State Listen -ErrorAction SilentlyContinue)
    if (-not $frontendReady) {
        return $false
    }

    $rootPattern = [regex]::Escape($root)
    $consoleReady = Get-CimInstance Win32_Process -Filter "Name = 'cmd.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -match $rootPattern -and
            $_.CommandLine -match 'start-dev\.cmd' -and
            (Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue).MainWindowHandle -ne 0
        } |
        Select-Object -First 1
    if (-not $consoleReady) {
        return $false
    }

    try {
        $response = Invoke-WebRequest -Uri $BackendProbeUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 300
    } catch {
        return $false
    }
}

function Open-Dashboard {
    Start-Process -FilePath (Join-Path $env:SystemRoot "explorer.exe") -ArgumentList $DashboardUrl | Out-Null
}

function Show-LaunchError {
    param([string]$Message)

    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        $Message,
        "Cleaning Dashboard",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
}

if (-not (Test-Path -LiteralPath $trainingScript)) {
    Show-LaunchError "Nie znaleziono pliku start-training-runtime.ps1 w:`n$root"
    exit 1
}
try {
    & $trainingScript
} catch {
    Show-LaunchError "Training Runtime nie wystartował:`n$($_.Exception.Message)"
    exit 1
}

if (Test-DashboardReady) {
    try {
        & node (Join-Path $root "scripts/kermit-autostart.js")
        if ($LASTEXITCODE -ne 0) { Write-Warning "Kermit is unavailable; opening the dashboard anyway." }
    } catch {
        Write-Warning "Kermit startup check failed: $($_.Exception.Message)"
    }
    Open-Dashboard
    exit 0
}

if (-not (Test-Path -LiteralPath $startScript)) {
    Show-LaunchError "Nie znaleziono pliku start-dev.cmd w:`n$root"
    exit 1
}

$arguments = "/d /c `"`"$startScript`"`""
$console = Start-Process `
    -FilePath $env:ComSpec `
    -ArgumentList $arguments `
    -WorkingDirectory $root `
    -WindowStyle Normal `
    -PassThru

$deadline = (Get-Date).AddSeconds([Math]::Max(5, $TimeoutSeconds))
while ((Get-Date) -lt $deadline) {
    if (Test-DashboardReady) {
        Open-Dashboard
        exit 0
    }
    if ($console.HasExited) {
        Show-LaunchError "Dashboard nie wystartował (kod $($console.ExitCode)). Uruchom start-dev.cmd ręcznie, aby zobaczyć pełny komunikat błędu."
        exit 1
    }
    Start-Sleep -Milliseconds 300
}

Show-LaunchError "Dashboard nie odpowiedział w ciągu $TimeoutSeconds sekund. Sprawdź zminimalizowane okno start-dev.cmd."
exit 1
