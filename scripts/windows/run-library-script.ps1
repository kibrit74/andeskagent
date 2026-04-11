param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptName
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$catalogPath = Join-Path $PSScriptRoot "script-library.json"
$LibraryRepoBase = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path -LiteralPath $catalogPath)) {
    throw "Script library catalog bulunamadi: $catalogPath"
}

$catalog = Get-Content -LiteralPath $catalogPath -Raw | ConvertFrom-Json
$item = $catalog | Where-Object { $_.name -eq $ScriptName } | Select-Object -First 1
if (-not $item) {
    throw "Script library item bulunamadi: $ScriptName"
}

function Invoke-StartProcessStep {
    param($Definition)
    $filePath = [string]$Definition.file_path
    $arguments = @()
    if ($Definition.arguments) {
        $arguments = @($Definition.arguments)
    }
    if ($arguments.Count -gt 0) {
        Start-Process -FilePath $filePath -ArgumentList $arguments | Out-Null
    }
    else {
        Start-Process -FilePath $filePath | Out-Null
    }
    if ($Definition.description) {
        Write-Output ([string]$Definition.description)
    }
    else {
        Write-Output ([string]$Definition.name)
    }
}

function Invoke-StartProcessCandidatesStep {
    param($Definition)
    $arguments = @()
    if ($Definition.arguments) {
        $arguments = @($Definition.arguments)
    }
    $errors = @()
    foreach ($candidate in @($Definition.file_candidates)) {
        try {
            if ($arguments.Count -gt 0) {
                Start-Process -FilePath ([string]$candidate) -ArgumentList $arguments | Out-Null
            }
            else {
                Start-Process -FilePath ([string]$candidate) | Out-Null
            }
            if ($Definition.description) {
                Write-Output ([string]$Definition.description)
            }
            else {
                Write-Output ([string]$Definition.name)
            }
            return
        }
        catch {
            $errors += $_.Exception.Message
        }
    }
    throw (($errors -join " | ").Trim())
}

function Invoke-StartShellTargetStep {
    param($Definition)
    $target = [string]$ExecutionContext.InvokeCommand.ExpandString([string]$Definition.target)
    Start-Process -FilePath $target | Out-Null
    if ($Definition.description) {
        Write-Output ([string]$Definition.description)
    }
    else {
        Write-Output ([string]$Definition.name)
    }
}

function Invoke-StopProcessStep {
    param($Definition)
    $names = @($Definition.process_names)
    foreach ($name in $names) {
        Stop-Process -Name ([string]$name) -Force -ErrorAction SilentlyContinue
    }
    if ($Definition.description) {
        Write-Output ([string]$Definition.description)
    }
    else {
        Write-Output ([string]$Definition.name)
    }
}

function Invoke-CommandCaptureStep {
    param($Definition)
    $command = [string]$Definition.command
    $arguments = @()
    if ($Definition.arguments) {
        $arguments = @($Definition.arguments)
    }
    $global:LASTEXITCODE = 0
    $output = & $command @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw (($output | Out-String).Trim())
    }
    ($output | Out-String).Trim()
}

function Invoke-InlinePowerShellStep {
    param($Definition)
    $scriptText = [string]$Definition.script
    $global:LASTEXITCODE = 0
    $output = Invoke-Expression $scriptText 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw (($output | Out-String).Trim())
    }
    ($output | Out-String).Trim()
}

switch ([string]$item.handler) {
    "start_process" { Invoke-StartProcessStep -Definition $item; break }
    "start_process_candidates" { Invoke-StartProcessCandidatesStep -Definition $item; break }
    "start_shell_target" { Invoke-StartShellTargetStep -Definition $item; break }
    "stop_process" { Invoke-StopProcessStep -Definition $item; break }
    "run_command_capture" { Invoke-CommandCaptureStep -Definition $item; break }
    "powershell_inline" { Invoke-InlinePowerShellStep -Definition $item; break }
    default { throw "Desteklenmeyen script handler: $($item.handler)" }
}
