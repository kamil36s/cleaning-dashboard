param([Parameter(Mandatory=$true)][string]$Agent, [Parameter(Mandatory=$true)][string]$Task, [switch]$Sync)
. "$PSScriptRoot/git-common.ps1"
$lock = Enter-GitLock
try {
    Assert-Idle
    Assert-Clean
    $previous = Get-Branch
    $branch = Get-TaskBranch $Agent $Task
    if (@(Invoke-Git for-each-ref '--format=%(refname:short)' refs/heads/) -contains $branch) { throw "Branch already exists: $branch" }
    Ensure-Dev
    Invoke-Git checkout --no-overwrite-ignore dev | Out-Host
    if ($Sync) {
        if (@(Invoke-Git remote) -notcontains 'origin') { throw 'Sync requested but origin is not configured; stopped on dev.' }
        Invoke-Git fetch origin | Out-Host
        Invoke-Git merge --ff-only refs/remotes/origin/dev | Out-Host
    }
    Invoke-Git checkout --no-overwrite-ignore -b $branch refs/heads/dev | Out-Host
    Write-Host "Current branch: $branch`nBase commit: $(Invoke-Git rev-parse HEAD)`nLatest build: $(Get-LatestBuild)`nWorking tree: clean"
} finally { $lock.Dispose() }
