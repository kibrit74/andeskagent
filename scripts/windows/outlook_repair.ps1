# outlook_repair.ps1 — Outlook temel onarim akisi
# Outlook surecini kapatir, onbellegi temizler ve yeniden baslatir

$ErrorActionPreference = "SilentlyContinue"

Write-Output "Outlook onarim akisi baslatiliyor..."

# 1. Outlook surecini kapat
$outlookProcess = Get-Process -Name "OUTLOOK" -ErrorAction SilentlyContinue
if ($outlookProcess) {
    Write-Output "Outlook sureci kapatiliyor..."
    Stop-Process -Name "OUTLOOK" -Force
    Start-Sleep -Seconds 3
    Write-Output "Outlook sureci kapatildi."
} else {
    Write-Output "Outlook sureci zaten calismiyor."
}

# 2. Outlook onbellek dosyalarini temizle
$localAppData = $env:LOCALAPPDATA
$outlookCachePaths = @(
    "$localAppData\Microsoft\Outlook\RoamCache",
    "$localAppData\Microsoft\Outlook\Offline Address Books"
)

$cleanedFiles = 0
foreach ($cachePath in $outlookCachePaths) {
    if (Test-Path $cachePath) {
        $files = Get-ChildItem -Path $cachePath -Recurse -File -ErrorAction SilentlyContinue
        foreach ($file in $files) {
            try {
                Remove-Item -Path $file.FullName -Force -ErrorAction Stop
                $cleanedFiles++
            } catch {}
        }
        Write-Output "Temizlendi: $cachePath"
    }
}

# 3. OST dosyasini kontrol et (silmeden boyutunu raporla)
$ostFiles = Get-ChildItem -Path "$localAppData\Microsoft\Outlook" -Filter "*.ost" -ErrorAction SilentlyContinue
foreach ($ost in $ostFiles) {
    $sizeMB = [math]::Round($ost.Length / 1MB, 2)
    Write-Output "OST dosyasi: $($ost.Name) — $sizeMB MB"
    if ($sizeMB -gt 5000) {
        Write-Output "UYARI: OST dosyasi cok buyuk ($sizeMB MB). Manuel mudahale gerekebilir."
    }
}

# 4. ScanPST (Inbox Repair Tool) var mi kontrol et
$scanPstPaths = @(
    "${env:ProgramFiles}\Microsoft Office\root\Office16\SCANPST.EXE",
    "${env:ProgramFiles(x86)}\Microsoft Office\root\Office16\SCANPST.EXE",
    "${env:ProgramFiles}\Microsoft Office\Office16\SCANPST.EXE"
)
$scanPstFound = $false
foreach ($path in $scanPstPaths) {
    if (Test-Path $path) {
        Write-Output "ScanPST bulundu: $path"
        Write-Output "Gerekirse manuel calistirabilirsiniz."
        $scanPstFound = $true
        break
    }
}
if (-not $scanPstFound) {
    Write-Output "ScanPST bulunamadi."
}

Write-Output ""
Write-Output "Temizlenen onbellek dosyasi: $cleanedFiles"
Write-Output "Outlook onarim akisi tamamlandi."
Write-Output "Outlook'u yeniden baslatabilirsiniz."
