param([Parameter(Mandatory=$true)][string]$Agent, [Parameter(Mandatory=$true)][string]$Task, [Parameter(Mandatory=$true)][string]$Path)
. "$PSScriptRoot/git-common.ps1"
$lock = Enter-GitLock
try {
    Assert-Idle
    Assert-Clean
    $branch = Get-TaskBranch $Agent $Task
    $target = [IO.Path]::GetFullPath($Path)
    if ($target.TrimEnd('\','/') -eq $repoRoot.TrimEnd('\','/') -or $target.StartsWith($repoRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Worktree must be outside the primary working directory.' }
    if (Test-Path -LiteralPath $target) { throw 'Choose a new worktree directory.' }
    Ensure-Dev
    Invoke-Git worktree add -b $branch $target refs/heads/dev | Out-Host
    Write-Host "Worktree: $target`nBranch: $branch`nBase: $(Invoke-Git rev-parse dev)"
} finally { $lock.Dispose() }
