param([switch]$Merge)
. "$PSScriptRoot/git-common.ps1"
$lock = Enter-GitLock
try {
    Assert-Idle
    $branch = Get-Branch
    if ($branch -notmatch '^ai/[^/]+/.+') { throw 'Finish requires ai/<agent>/<task>.' }
    Invoke-Git rev-parse --verify refs/heads/dev | Out-Null
    New-Checkpoint | Out-Host
    Assert-Clean
    Write-Host "Branch: $branch`nBase branch: dev`nCommits ahead: $(Invoke-Git rev-list --count dev..HEAD)`nLatest build: $(Get-LatestBuild)"
    Invoke-Git diff --name-status dev...HEAD | Out-Host
    Invoke-Git diff --stat dev...HEAD | Out-Host
    if ($Merge) {
        Invoke-Git checkout --no-overwrite-ignore dev | Out-Host
        Invoke-Git merge --no-ff --no-edit $branch | Out-Host
        Write-Host 'Merged into dev. Task branch retained.'
    } else { Write-Host 'Review before running again with -Merge.' }
} finally { $lock.Dispose() }
