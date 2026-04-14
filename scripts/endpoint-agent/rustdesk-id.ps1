function Get-TeknikajanRustDeskId {
    param(
        [string]$RustDeskPath = ""
    )

    $candidates = @()

    if (-not [string]::IsNullOrWhiteSpace($RustDeskPath)) {
        $candidates += $RustDeskPath
    }

    $pathCommand = Get-Command "rustdesk.exe" -ErrorAction SilentlyContinue
    if ($pathCommand) {
        $candidates += $pathCommand.Source
    }

    $installRoots = @(
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)},
        $env:LOCALAPPDATA
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    foreach ($root in $installRoots) {
        $candidates += Join-Path $root "RustDesk\RustDesk.exe"
        $candidates += Join-Path $root "RustDesk\rustdesk.exe"
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate)) {
            continue
        }

        $output = & $candidate --get-id 2>$null
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($output)) {
            return (($output | Select-Object -First 1) -as [string]).Trim()
        }
    }

    return ""
}
