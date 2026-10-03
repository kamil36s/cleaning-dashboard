$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
function Invoke-Git {
    $Arguments = $args
    $oldPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $result = & git -C $repoRoot @Arguments 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $oldPreference
    if ($code -ne 0) { throw "git $($Arguments -join ' ') failed ($code): $($result -join "`n")" }
    $result | ForEach-Object { "$_" }
}
function Get-Branch { Invoke-Git symbolic-ref --quiet --short HEAD }
function Assert-Clean {
    if (@(Invoke-Git status --porcelain=v1 --untracked-files=all).Count) {
        throw 'Working tree is dirty. Run scripts/save.ps1 first; no files were discarded.'
    }
}
function Assert-Idle {
    foreach ($marker in @('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply','BISECT_LOG')) {
        $path = Invoke-Git rev-parse --git-path $marker
        if (-not [IO.Path]::IsPathRooted($path)) { $path = Join-Path $repoRoot $path }
        if (Test-Path -LiteralPath $path) { throw "Finish or abort the existing Git operation first: $marker" }
    }
    if (@(Invoke-Git ls-files --unmerged).Count) { throw 'Unresolved index conflicts. Resolve them first.' }
}
function Enter-GitLock {
    $common = Invoke-Git rev-parse --git-common-dir
    if (-not [IO.Path]::IsPathRooted($common)) { $common = Join-Path $repoRoot $common }
    try { return [IO.File]::Open((Join-Path $common 'dashboard-backup.lock'), 'OpenOrCreate', 'ReadWrite', 'None') }
    catch [IO.IOException] { throw 'Another Git helper is running. Retry when it finishes.' }
}
function Get-BuildTags {
    @(Invoke-Git tag --list 'build-*') | Where-Object { $_ -cmatch '^build-\d{4,}$' } | Sort-Object { [long]$_.Substring(6) }
}
function Get-LatestBuild {
    $tags = @(Get-BuildTags)
    if ($tags.Count) { $tags[-1] } else { '(none)' }
}
function Get-TaskBranch([string]$Agent, [string]$Task) {
    $a = ($Agent.ToLowerInvariant() -replace '[^a-z0-9]+','-').Trim('-')
    $t = ($Task.ToLowerInvariant() -replace '[^a-z0-9]+','-').Trim('-')
    if (-not $a -or -not $t) { throw 'Agent and task must contain letters or digits.' }
    $name = "ai/$a/$t"
    Invoke-Git check-ref-format --branch $name | Out-Null
    return $name
}
function Ensure-Dev {
    $branches = @(Invoke-Git for-each-ref '--format=%(refname:short)' refs/heads/)
    if ($branches -notcontains 'dev') { Invoke-Git branch dev refs/heads/main | Out-Host }
}
function Assert-SafeCandidates {
    # Includes tracked files: .gitignore alone cannot protect already tracked secrets.
    $paths = @(Invoke-Git -c core.quotePath=false ls-files --cached --others --exclude-standard)
    foreach ($path in $paths) {
        if ($path -match '(^|/)(\.env($|\.)|credentials[^/]*$|id_rsa$|id_ed25519$)' -and $path -notmatch '(^|/)\.env\.example$') {
            throw "Potential secret path: $path. Review/untrack it before checkpointing."
        }
        if ($path -match '\.(pem|key|p12|pfx|jks|keystore|sqlite|sqlite3|db)([.-].*)?$') { throw "Private key/database candidate: $path" }
        $full = Join-Path $repoRoot $path
        if ((Test-Path -LiteralPath $full -PathType Leaf) -and (Get-Item -LiteralPath $full).Length -gt 50MB) { throw "File exceeds 50 MB: $path. Review ignore rules first." }
    }
}
function New-Checkpoint([switch]$AllowMain) {
    Assert-Idle
    $branch = Get-Branch
    $changes = @(Invoke-Git status --porcelain=v1 --untracked-files=all)
    if (-not $changes.Count) { Write-Host 'No changes to checkpoint.'; return }
    if ($branch -eq 'main' -and -not $AllowMain -and $env:DASHBOARD_ALLOW_MAIN -ne '1') { throw 'main is protected; use dev or ai/<agent>/<task>. Conscious emergency: -AllowMain.' }
    Assert-SafeCandidates
    $tags = @(Get-BuildTags)
    $number = if ($tags.Count) { [long]$tags[-1].Substring(6) + 1 } else { 1 }
    $tag = 'build-{0:D4}' -f $number
    $beforeHead = Invoke-Git rev-parse HEAD
    $indexPath = Invoke-Git rev-parse --git-path index
    if (-not [IO.Path]::IsPathRooted($indexPath)) { $indexPath = Join-Path $repoRoot $indexPath }
    $indexBytes = if (Test-Path -LiteralPath $indexPath) { [IO.File]::ReadAllBytes($indexPath) } else { $null }
    $changelogPath = Join-Path $repoRoot 'CHANGELOG-AUTO.md'
    $logBytes = if (Test-Path -LiteralPath $changelogPath) { [IO.File]::ReadAllBytes($changelogPath) } else { $null }
    $committed = $false
    try {
        Invoke-Git -c core.safecrlf=false add -A -- . | Out-Host
        $names = @(Invoke-Git diff --cached --name-status --find-renames)
        if (-not $names.Count) { Write-Host 'No changes to checkpoint.'; return }
        # Only print paths on detection, never secret values.
        $pattern = '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|sk-(proj-)?[A-Za-z0-9_-]{40,}|AIza[A-Za-z0-9_-]{30,}'
        $oldPreference = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
        $secretPaths = & git -C $repoRoot grep --cached -l -I -E -e $pattern -- . 2>&1
        $scanCode = $LASTEXITCODE; $ErrorActionPreference = $oldPreference
        if ($scanCode -eq 0) { throw "Potential credentials in staged paths: $($secretPaths -join ', ')" }
        if ($scanCode -ne 1) { throw 'Staged credential scan failed.' }
        $groups = [ordered]@{ Added=@(); Modified=@(); Deleted=@(); Renamed=@(); Other=@() }
        foreach ($line in $names) {
            $parts = $line -split "`t"
            $key = switch ($parts[0].Substring(0,1)) { A {'Added'} M {'Modified'} D {'Deleted'} R {'Renamed'} default {'Other'} }
            $groups[$key] += '- ' + (($parts | Select-Object -Skip 1) -join ' -> ')
        }
        $insertions = 0L; $deletions = 0L; $binary = 0
        foreach ($line in @(Invoke-Git diff --cached --numstat --find-renames)) {
            $parts = $line -split "`t"
            if ($parts[0] -eq '-') { $binary++ } else { $insertions += [long]$parts[0]; $deletions += [long]$parts[1] }
        }
        $entry = @("## $tag - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')", '', "Branch: $branch", '')
        foreach ($key in $groups.Keys) { $entry += "### $key"; $entry += $groups[$key]; $entry += '' }
        $entry += @('### Stats', "- $($names.Count) files changed", "- $insertions insertions", "- $deletions deletions", "- $binary binary files", '- Stats describe staged input before this generated entry.', '', '---', '')
        $oldLog = if ($null -ne $logBytes) { [Text.Encoding]::UTF8.GetString($logBytes).TrimStart([char]0xfeff) } else { '' }
        [IO.File]::WriteAllText($changelogPath, (($entry -join "`n") + "`n" + $oldLog), (New-Object Text.UTF8Encoding($false)))
        Invoke-Git add -- CHANGELOG-AUTO.md | Out-Host
        $oldOverride = $env:DASHBOARD_ALLOW_MAIN
        try {
            if ($AllowMain) { $env:DASHBOARD_ALLOW_MAIN = '1' }
            Invoke-Git commit -m "checkpoint($tag): project changes" | Out-Host
        } finally { $env:DASHBOARD_ALLOW_MAIN = $oldOverride }
        $committed = $true
        $commit = Invoke-Git rev-parse HEAD
        try { Invoke-Git tag -a $tag $commit -m "Dashboard checkpoint $tag" | Out-Host }
        catch { throw "Commit $commit is safe, but tag failed. Repair with: git tag -a $tag $commit -m '$tag'. $($_.Exception.Message)" }
        Write-Host "Checkpoint: $tag ($commit)"
        return $tag
    } catch {
        if (-not $committed -and (Invoke-Git rev-parse HEAD) -eq $beforeHead) {
            if ($null -ne $indexBytes) { [IO.File]::WriteAllBytes($indexPath, $indexBytes) }
            elseif (Test-Path -LiteralPath $indexPath) { Remove-Item -LiteralPath $indexPath }
            if ($null -ne $logBytes) { [IO.File]::WriteAllBytes($changelogPath, $logBytes) }
            elseif (Test-Path -LiteralPath $changelogPath) { Remove-Item -LiteralPath $changelogPath }
        }
        throw
    }
}
