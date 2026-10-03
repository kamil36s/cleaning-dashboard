. "$PSScriptRoot/git-common.ps1"
Invoke-Git tag --list 'build-*' 'save-*' 'auto-*' --sort=-creatordate '--format=%(creatordate:iso8601)  %(refname:short)  %(objectname:short)' | Select-Object -First 30
