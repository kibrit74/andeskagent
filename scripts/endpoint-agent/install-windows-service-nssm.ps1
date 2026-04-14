param(
    [Parameter(Mandatory = $true)]
    [string]$NssmPath,

    [Parameter(Mandatory = $true)]
    [string]$ApiBaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$OperatorToken,

    [string]$RustDeskId = "",
    [string]$RustDeskPath = "",
    [string]$ServiceName = "TeknikajanEndpointAgent",
    [string]$AgentExePath = "dist\endpoint-agent\TeknikajanEndpointAgent.exe",
    [string]$ConfigPath = "config\endpoint_agent.json",
    [string[]]$AllowedActions = @("get_system_status", "collect_logs"),
    [string[]]$AllowedScripts = @()
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    throw "Windows Service kurmak icin PowerShell'i Administrator olarak calistirin."
}

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ResolvedNssm = (Resolve-Path $NssmPath).Path
$ResolvedAgentExe = Join-Path $ProjectRoot $AgentExePath
$ResolvedConfig = Join-Path $ProjectRoot $ConfigPath
$LogDir = Join-Path $ProjectRoot "logs"
$RustDeskHelper = Join-Path $PSScriptRoot "rustdesk-id.ps1"

. $RustDeskHelper

if (-not (Test-Path $ResolvedAgentExe)) {
    throw "Endpoint agent exe bulunamadi: $ResolvedAgentExe"
}
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
}

Set-Location $ProjectRoot

if ([string]::IsNullOrWhiteSpace($RustDeskId)) {
    $RustDeskId = Get-TeknikajanRustDeskId -RustDeskPath $RustDeskPath
}

if (-not (Test-Path $ResolvedConfig)) {
    & $ResolvedAgentExe provision $ApiBaseUrl $OperatorToken --config-path $ResolvedConfig --rustdesk-id $RustDeskId
    if ($LASTEXITCODE -ne 0) {
        throw "Endpoint agent provision basarisiz."
    }
} else {
    & $ResolvedAgentExe sync-profile --config-path $ResolvedConfig --rustdesk-id $RustDeskId
    if ($LASTEXITCODE -ne 0) {
        throw "Endpoint agent profil senkronizasyonu basarisiz."
    }
}

$config = Get-Content -LiteralPath $ResolvedConfig -Raw | ConvertFrom-Json
$config.allowed_actions = @($AllowedActions)
$config.allowed_scripts = @($AllowedScripts)
$config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ResolvedConfig -Encoding UTF8

& $ResolvedNssm install $ServiceName $ResolvedAgentExe "run" "--config-path" $ResolvedConfig
& $ResolvedNssm set $ServiceName AppDirectory $ProjectRoot
& $ResolvedNssm set $ServiceName DisplayName "Teknikajan Endpoint Agent"
& $ResolvedNssm set $ServiceName Description "Teknikajan backend komut kuyruğunu dinleyen endpoint agent."
& $ResolvedNssm set $ServiceName Start SERVICE_AUTO_START
& $ResolvedNssm set $ServiceName AppStdout (Join-Path $LogDir "endpoint-agent-service.out.log")
& $ResolvedNssm set $ServiceName AppStderr (Join-Path $LogDir "endpoint-agent-service.err.log")
& $ResolvedNssm set $ServiceName AppRotateFiles 1
& $ResolvedNssm set $ServiceName AppRotateBytes 1048576
& $ResolvedNssm start $ServiceName

Write-Output "Teknikajan endpoint agent servisi kuruldu: $ServiceName"
Write-Output "Config: $ResolvedConfig"
Write-Output "Device ID: $($config.device_id)"
