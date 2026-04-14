param(
    [Parameter(Mandatory = $true)]
    [string]$ApiBaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$OperatorToken,

    [string]$RustDeskId = "",
    [string]$RustDeskPath = "",
    [string]$TaskName = "TeknikajanEndpointAgent",
    [string]$ConfigPath = "config\endpoint_agent.json",
    [string]$PythonPath = ".venv\Scripts\python.exe",
    [string[]]$AllowedActions = @("get_system_status", "collect_logs"),
    [string[]]$AllowedScripts = @()
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ResolvedPython = Join-Path $ProjectRoot $PythonPath
$ResolvedConfig = Join-Path $ProjectRoot $ConfigPath
$RustDeskHelper = Join-Path $PSScriptRoot "rustdesk-id.ps1"

. $RustDeskHelper

if (-not (Test-Path $ResolvedPython)) {
    throw "Python bulunamadi: $ResolvedPython"
}

Set-Location $ProjectRoot

if ([string]::IsNullOrWhiteSpace($RustDeskId)) {
    $RustDeskId = Get-TeknikajanRustDeskId -RustDeskPath $RustDeskPath
}

if (-not (Test-Path $ResolvedConfig)) {
    & $ResolvedPython -m endpoint_agent provision $ApiBaseUrl $OperatorToken --config-path $ResolvedConfig --rustdesk-id $RustDeskId
    if ($LASTEXITCODE -ne 0) {
        throw "Endpoint agent provision basarisiz."
    }
} else {
    & $ResolvedPython -m endpoint_agent sync-profile --config-path $ResolvedConfig --rustdesk-id $RustDeskId
    if ($LASTEXITCODE -ne 0) {
        throw "Endpoint agent profil senkronizasyonu basarisiz."
    }
}

$config = Get-Content -LiteralPath $ResolvedConfig -Raw | ConvertFrom-Json
$config.allowed_actions = @($AllowedActions)
$config.allowed_scripts = @($AllowedScripts)
$config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $ResolvedConfig -Encoding UTF8

$Action = New-ScheduledTaskAction `
    -Execute $ResolvedPython `
    -Argument "-m endpoint_agent run --config-path `"$ResolvedConfig`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -AtStartup
$Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Output "Teknikajan endpoint agent task kuruldu: $TaskName"
Write-Output "Config: $ResolvedConfig"
Write-Output "Device ID: $($config.device_id)"
