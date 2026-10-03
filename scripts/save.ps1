param(
    [ValidateSet("save", "auto")][string]$Prefix = "save",
    [switch]$AllowMain,
    [switch]$Push
)
. "$PSScriptRoot/git-common.ps1"
$lock = Enter-GitLock
try {
    $tag = New-Checkpoint -AllowMain:$AllowMain
    if ($Push) {
        $branch = Get-Branch
        if (@(Invoke-Git remote) -notcontains 'origin') { throw 'Local checkpoint is safe. Push requested, but origin is not configured.' }
        if (-not (Invoke-Git for-each-ref '--format=%(upstream)' "refs/heads/$branch")) {
            Write-Host "No upstream; explicit push sets origin/$branch as upstream."
        }
        $refs = @("HEAD:refs/heads/$branch")
        if ($tag) { $refs += "refs/tags/$tag" }
        Invoke-Git push --atomic --set-upstream origin @refs | Out-Host
    }
} finally { $lock.Dispose() }
