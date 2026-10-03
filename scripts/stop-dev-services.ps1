param(
    [Parameter(Mandatory = $true)]
    [string]$Root,

    [ValidateSet("All", "Api")]
    [string]$Service = "All"
)

. (Join-Path $PSScriptRoot "dev-console.ps1")

$ErrorActionPreference = "Stop"
$resolvedRoot = [IO.Path]::GetFullPath($Root).TrimEnd("\")
$rootPattern = [regex]::Escape($resolvedRoot)
$allProcesses = @(Get-CimInstance Win32_Process)

if ($Service -eq "Api") {
    $entryPattern = "server\.py|dev-service\.js[\""']?\s+api(?:\s|$)"
    $ports = @(8000)
} else {
    $entryPattern = "server\.py|run_network_monitor\.py|scan_ble\.py|dev-service\.js|vite[\\/]bin[\\/]vite\.js|npm-cli\.js[\""']?\s+run\s+dev:lan"
    $ports = @(8000, 8765, 5173)
}

$processById = @{}
foreach ($process in $allProcesses) {
    $processById[[int]$process.ProcessId] = $process
}

$targets = @(
    $allProcesses |
        Where-Object {
            if ($_.ProcessId -eq $PID -or -not $_.CommandLine -or $_.CommandLine -notmatch $entryPattern) {
                return $false
            }
            $current = $_
            $seen = @{}
            while ($current -and -not $seen.ContainsKey([int]$current.ProcessId)) {
                $seen[[int]$current.ProcessId] = $true
                if ($current.CommandLine -and $current.CommandLine -match $rootPattern) {
                    return $true
                }
                $current = $processById[[int]$current.ParentProcessId]
            }
            return $false
        } |
        Sort-Object ProcessId -Unique
)

# Older launchers started Python with a relative script path. If their parent
# console disappeared, the orphan no longer contains the project root in its
# process ancestry and was incorrectly reported as an unrelated port conflict.
$legacyEntryByPort = @{
    8000 = '(?i)(?:^|\s)server\.py(?:\s|$)'
    8765 = '(?i)(?:^|\s)run_network_monitor\.py(?:\s|$)'
}
$knownTargetIds = @{}
foreach ($target in $targets) {
    $knownTargetIds[[int]$target.ProcessId] = $true
}
foreach ($port in $ports) {
    $legacyPattern = $legacyEntryByPort[[int]$port]
    if (-not $legacyPattern) {
        continue
    }
    $ownerIds = @(
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
    foreach ($ownerPid in $ownerIds) {
        if ($knownTargetIds.ContainsKey([int]$ownerPid)) {
            continue
        }
        $owner = $processById[[int]$ownerPid]
        if ($owner -and $owner.CommandLine -match $legacyPattern) {
            Write-DevStatus "Found legacy orphan for port $port (PID $ownerPid)." "Yellow"
            $targets += $owner
            $knownTargetIds[[int]$ownerPid] = $true
        }
    }
}
$targets = @($targets | Sort-Object ProcessId -Unique)

if ($targets.Count -gt 0) {
    $ids = $targets | ForEach-Object { [int]$_.ProcessId }
    Write-DevStatus "Stopping project process(es): $($ids -join ', ')"
    $ids | ForEach-Object { Stop-Process -Id $_ -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 350
    $ids | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue } |
        ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 350
}

$conflicts = @()
foreach ($port in $ports) {
    $listeners = @(
        Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
    foreach ($ownerPid in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerPid" -ErrorAction SilentlyContinue
        $name = if ($process.Name) { $process.Name } else { "unknown" }
        $conflicts += "port $port -> $name (PID $ownerPid)"
    }
}

if ($conflicts.Count -gt 0) {
    Write-DevStatus "Startup stopped: required port is occupied by a non-project process." "Red"
    $conflicts | ForEach-Object { Write-DevStatus "  $_" "Red" }
    Write-DevStatus "No unrelated process was terminated." "Yellow"
    exit 2
}

if ($targets.Count -eq 0) {
    Write-DevStatus "No previous project services were running."
} else {
    Write-DevStatus "Previous project services stopped."
}
