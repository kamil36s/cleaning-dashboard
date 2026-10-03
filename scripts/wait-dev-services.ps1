param(
    [int]$TimeoutSeconds = 30
)

. (Join-Path $PSScriptRoot "dev-console.ps1")

$ErrorActionPreference = "Stop"
$required = @(
    @{
        Name = "API"
        Port = 8000
        ProbeUrl = "http://127.0.0.1:8000/api/events?sync=0&past=0&local=1&google=0&days=1"
    },
    @{ Name = "Network Monitor"; Port = 8765 }
)
$pending = @{}
foreach ($service in $required) {
    $pending[[int]$service.Port] = $service
}

$deadline = (Get-Date).AddSeconds([Math]::Max(1, $TimeoutSeconds))
while ($pending.Count -gt 0 -and (Get-Date) -lt $deadline) {
    foreach ($port in @($pending.Keys)) {
        $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
        if ($listener) {
            $service = $pending[$port]
            $ready = $true
            if ($service.ProbeUrl) {
                try {
                    $response = Invoke-WebRequest -Uri $service.ProbeUrl -UseBasicParsing -TimeoutSec 2
                    $ready = $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
                } catch {
                    $ready = $false
                }
            }
            if (-not $ready) {
                continue
            }
            Write-DevStatus "$($service.Name) ready on port $port."
            $pending.Remove($port)
        }
    }
    if ($pending.Count -gt 0) {
        Start-Sleep -Milliseconds 200
    }
}

if ($pending.Count -gt 0) {
    $missing = $pending.GetEnumerator() | ForEach-Object { "$($_.Value.Name) ($($_.Key))" }
    Write-DevStatus "Startup timed out waiting for: $($missing -join ', ')." "Red"
    exit 1
}

Write-DevStatus "Backends ready. Starting Vite without proxy connection noise."
