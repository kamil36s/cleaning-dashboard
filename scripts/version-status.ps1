. "$PSScriptRoot/git-common.ps1"
$branch = Get-Branch
$changes = @(Invoke-Git status --porcelain=v1 --untracked-files=all)
$state = if ($changes.Count) { "$($changes.Count) changed/untracked paths" } else { 'clean' }
$branches = @(Invoke-Git for-each-ref '--format=%(refname:short)' refs/heads/)
$ahead = if ($branches -contains 'dev') { Invoke-Git rev-list --count dev..HEAD } else { 'n/a (dev created on first task)' }
$remote = if (@(Invoke-Git remote) -contains 'origin') { 'origin configured' } else { 'origin not configured' }
$hooks = @(Invoke-Git config --get-regexp '^core\.')
$enabled = if ($hooks -contains 'core.hookspath .githooks' -and (Test-Path (Join-Path $repoRoot '.githooks/pre-commit'))) { 'enabled' } else { 'not enabled' }
Write-Host "Current branch: $branch`nLatest build (repository-wide): $(Get-LatestBuild)`nWorking tree: $state`nCommits ahead of dev: $ahead`nRemote: $remote`nHooks: $enabled"
Write-Host "HEAD: $(Invoke-Git rev-parse --short HEAD)"
Invoke-Git tag --points-at HEAD | Out-Host
