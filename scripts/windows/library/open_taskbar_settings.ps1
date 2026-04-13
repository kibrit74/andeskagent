$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$runner = Join-Path $(Split-Path -Parent $scriptRoot) 'run-library-script.ps1'
powershell -ExecutionPolicy Bypass -File $runner -ScriptName "open_taskbar_settings"
