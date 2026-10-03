. "$PSScriptRoot/git-common.ps1"
$lock = Enter-GitLock
try {
    Assert-Idle
    Assert-Clean
    if ((Get-Branch) -ne 'main') { throw 'Run publication from the clean main worktree.' }
    if (@(Invoke-Git remote) -notcontains 'origin') { throw 'Origin is not configured.' }

    Invoke-Git fetch origin main master | Out-Host
    $remoteMain = Invoke-Git rev-parse refs/remotes/origin/main
    $remoteMaster = Invoke-Git rev-parse refs/remotes/origin/master
    if ($remoteMain -ne $remoteMaster) { throw 'Remote main and master differ. Review before publishing.' }
    $localMain = Invoke-Git rev-parse HEAD
    if ((Invoke-Git merge-base refs/remotes/origin/main main) -ne $remoteMain) {
        throw 'Local main diverged from origin/main. Review before publishing.'
    }
    Invoke-Git rev-parse --verify refs/heads/dev | Out-Null
    $devHead = Invoke-Git rev-parse dev
    $devAlreadyPublished = $devHead -eq (Invoke-Git merge-base main dev)
    if ($devAlreadyPublished -and $localMain -eq $remoteMain) {
        Write-Host 'Main is already current. Nothing to publish.'
        return
    }

    # A former local history contains a credential. Never reconnect that history
    # to the public branch through an older task branch.
    $unsafeCommit = '4ec89f780def1c4b2d387bf38ea60a780c4296bc'
    if (@(Invoke-Git rev-list main..dev) -contains $unsafeCommit) {
        throw 'Dev contains the archived credential-bearing history. Replay only the task changes onto current dev.'
    }
    if (-not $devAlreadyPublished) {
        $oldOverride = $env:DASHBOARD_ALLOW_MAIN
        try {
            $env:DASHBOARD_ALLOW_MAIN = '1'
            Invoke-Git merge --no-ff --no-edit dev | Out-Host
        } finally { $env:DASHBOARD_ALLOW_MAIN = $oldOverride }
    }

    # Check the complete published tree, including files untouched by this merge.
    $pattern = '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|sk-(proj-)?[A-Za-z0-9_-]{40,}|AIza[A-Za-z0-9_-]{30,}'
    $oldPreference = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $secretPaths = & git -C $repoRoot grep -l -I -E -e $pattern HEAD -- . 2>&1
    $scanCode = $LASTEXITCODE; $ErrorActionPreference = $oldPreference
    if ($scanCode -eq 0) { throw "Potential credentials in publication: $($secretPaths -join ', ')" }
    if ($scanCode -ne 1) { throw 'Publication credential scan failed.' }

    $tag = 'release/{0}' -f (Get-Date -Format 'yyyyMMdd-HHmmss')
    Invoke-Git tag -a $tag -m "Dashboard publication $tag" | Out-Host
    Invoke-Git push --atomic origin 'HEAD:refs/heads/main' 'HEAD:refs/heads/master' "refs/tags/$tag" | Out-Host
    Write-Host "Published main and master with backup tag $tag."
} finally { $lock.Dispose() }
