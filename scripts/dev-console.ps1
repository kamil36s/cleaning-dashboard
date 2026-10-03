function Write-DevStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message,

        [string]$Color = ""
    )

    $line = "{0} {1,-7} | {2}" -f (Get-Date -Format "HH:mm:ss"), "[SYS]", $Message
    if ($Color) {
        Write-Host $line -ForegroundColor $Color
    } else {
        Write-Host $line
    }
}
