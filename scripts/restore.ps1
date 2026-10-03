param([Parameter(Mandatory = $true, Position = 0)][Alias('Build')][string]$Tag)
. "$PSScriptRoot/git-common.ps1"
if ($Tag -cnotmatch '^(build-\d{4,}|(save|auto)-\d{8}-\d{6})$') { throw 'Use an existing build-XXXX, save-* or auto-* tag.' }
$lock = Enter-GitLock
try {
    Assert-Idle
    Assert-Clean
    $target = Invoke-Git rev-parse --verify "refs/tags/${Tag}^{commit}"
    $current = Invoke-Git rev-parse HEAD
    $branch = "recovery/$Tag"
    $branches = @(Invoke-Git for-each-ref '--format=%(refname:short)' refs/heads/)
    $suffix = 2
    while ($branches -contains $branch) { $branch = "recovery/$Tag-$suffix"; $suffix++ }
    Write-Host "Current version: $current`nRequested version: $Tag ($target)`nRecovery branch: $branch"
    Invoke-Git checkout --no-overwrite-ignore -b $branch $target | Out-Host
    Write-Host 'History preserved. Return with git switch <previous-branch>. Ignored databases are not restored by Git.'
} finally { $lock.Dispose() }
