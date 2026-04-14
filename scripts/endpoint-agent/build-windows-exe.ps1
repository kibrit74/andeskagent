param(
    [string]$PythonPath = ".venv\Scripts\python.exe",
    [string]$Name = "TeknikajanEndpointAgent",
    [string]$DistPath = "dist\endpoint-agent",
    [string]$WorkPath = "build\endpoint-agent"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ResolvedPython = Join-Path $ProjectRoot $PythonPath
$ResolvedDist = Join-Path $ProjectRoot $DistPath
$ResolvedWork = Join-Path $ProjectRoot $WorkPath
$EntryPoint = Join-Path $ProjectRoot "endpoint_agent\__main__.py"

if (-not (Test-Path $ResolvedPython)) {
    throw "Python bulunamadi: $ResolvedPython"
}
if (-not (Test-Path $EntryPoint)) {
    throw "Endpoint agent entrypoint bulunamadi: $EntryPoint"
}

Set-Location $ProjectRoot

& $ResolvedPython -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller kurulu degil. Once sunu calistirin: $ResolvedPython -m pip install -r requirements-build.txt"
}

& $ResolvedPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name $Name `
    --distpath $ResolvedDist `
    --workpath $ResolvedWork `
    --paths $ProjectRoot `
    $EntryPoint

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build basarisiz."
}

$ExePath = Join-Path $ResolvedDist "$Name.exe"
if (-not (Test-Path $ExePath)) {
    throw "Beklenen exe olusmadi: $ExePath"
}

Write-Output "Endpoint agent exe hazir: $ExePath"
