param(
    [Parameter(Mandatory = $true)]
    [string]$NssmPath,

    [string]$ServiceName = "TeknikajanEndpointAgent"
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    throw "Windows Service kaldirmak icin PowerShell'i Administrator olarak calistirin."
}

$ResolvedNssm = (Resolve-Path $NssmPath).Path

& $ResolvedNssm stop $ServiceName
& $ResolvedNssm remove $ServiceName confirm

Write-Output "Teknikajan endpoint agent servisi kaldirildi: $ServiceName"
