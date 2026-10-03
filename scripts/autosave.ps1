param(
    [ValidateRange(1,1440)][int]$Minutes = 20,
    [ValidateRange(1,86400)][int]$IntervalSeconds = 0,
    [ValidateRange(0,3600)][int]$QuietSeconds = 0,
    [switch]$Once
)
. "$PSScriptRoot/git-common.ps1"
$interval = if ($IntervalSeconds) { $IntervalSeconds } else { $Minutes * 60 }
Write-Host "Git watcher: every $interval seconds. Foreground only; Ctrl+C stops. No main override."
do {
    if (-not $Once) { Start-Sleep -Seconds $interval }
    & "$PSScriptRoot/save.ps1" -Prefix auto
} while (-not $Once)
