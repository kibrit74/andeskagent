param(
    [string]$ConfigPath = "config\endpoint_agent.json",
    [string]$PythonPath = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ResolvedPython = Join-Path $ProjectRoot $PythonPath
$ResolvedConfig = Join-Path $ProjectRoot $ConfigPath

if (-not (Test-Path $ResolvedPython)) {
    throw "Python bulunamadi: $ResolvedPython"
}
if (-not (Test-Path $ResolvedConfig)) {
    throw "Endpoint agent config bulunamadi: $ResolvedConfig"
}

Set-Location $ProjectRoot
& $ResolvedPython -m endpoint_agent run-once --config-path $ResolvedConfig
