# office_repair.ps1 — Microsoft Office temel onarim akisi
# Office uygulamalarini kapatir ve hizli onarim baslatir

$ErrorActionPreference = "SilentlyContinue"

Write-Output "Office onarim akisi baslatiliyor..."

# 1. Office sureclerini kapat
$officeProcesses = @("WINWORD", "EXCEL", "POWERPNT", "OUTLOOK", "MSACCESS", "ONENOTE", "MSPUB")
$closedCount = 0

foreach ($procName in $officeProcesses) {
    $proc = Get-Process -Name $procName -ErrorAction SilentlyContinue
    if ($proc) {
        Stop-Process -Name $procName -Force -ErrorAction SilentlyContinue
        $closedCount++
        Write-Output "Kapatildi: $procName"
    }
}

if ($closedCount -eq 0) {
    Write-Output "Acik Office uygulamasi bulunamadi."
} else {
    Start-Sleep -Seconds 2
    Write-Output "$closedCount Office uygulamasi kapatildi."
}

# 2. Office onbellek temizligi
$officeCachePaths = @(
    "$env:LOCALAPPDATA\Microsoft\Office\16.0\OfficeFileCache",
    "$env:LOCALAPPDATA\Microsoft\Office\OTele",
    "$env:APPDATA\Microsoft\Templates\~*.tmp"
)

$cleanedFiles = 0
foreach ($cachePath in $officeCachePaths) {
    if (Test-Path $cachePath) {
        $items = Get-ChildItem -Path $cachePath -Recurse -File -ErrorAction SilentlyContinue
        foreach ($item in $items) {
            try {
                Remove-Item -Path $item.FullName -Force -ErrorAction Stop
                $cleanedFiles++
            } catch {}
        }
    }
}
Write-Output "Temizlenen onbellek dosyasi: $cleanedFiles"

# 3. Office Click-to-Run onarim komutu (hizli onarim)
$clickToRunPath = "${env:ProgramFiles}\Common Files\Microsoft Shared\ClickToRun\OfficeC2RClient.exe"
if (Test-Path $clickToRunPath) {
    Write-Output "Office Click-to-Run bulundu."
    Write-Output "Hizli onarim baslatiliyor..."
    try {
        Start-Process -FilePath $clickToRunPath -ArgumentList "/repair QuickRepair" -Wait -NoNewWindow -ErrorAction Stop
        Write-Output "Hizli onarim tamamlandi."
    } catch {
        Write-Output "Hizli onarim baslatildi ancak sonuc dogrulanamadi."
        Write-Output "Manuel kontrol icin: Ayarlar > Uygulamalar > Microsoft Office > Degistir > Hizli Onarim"
    }
} else {
    Write-Output "Office Click-to-Run bulunamadi. MSI kurulumu olabilir."
    Write-Output "Manuel onarim icin: Denetim Masasi > Programlar > Microsoft Office > Degistir"
}

# 4. Normal.dotm sablonunu yedekle (bozuk olabilir)
$normalDotm = "$env:APPDATA\Microsoft\Templates\Normal.dotm"
if (Test-Path $normalDotm) {
    $backupPath = "$env:APPDATA\Microsoft\Templates\Normal.dotm.bak"
    Copy-Item -Path $normalDotm -Destination $backupPath -Force -ErrorAction SilentlyContinue
    Write-Output "Normal.dotm yedeklendi: $backupPath"
}

Write-Output ""
Write-Output "Office onarim akisi tamamlandi."
Write-Output "Office uygulamalarini yeniden baslatabilirsiniz."
