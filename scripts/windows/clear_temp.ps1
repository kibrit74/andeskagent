# clear_temp.ps1 — Windows temp dosyalarini temizleme
# Guvenli: Sadece kullanici temp klasorunu hedefler

$ErrorActionPreference = "SilentlyContinue"

$tempPaths = @(
    $env:TEMP,
    "$env:LOCALAPPDATA\Temp",
    "$env:WINDIR\Temp"
)

$totalRemoved = 0
$totalSize = 0

foreach ($tempPath in $tempPaths) {
    if (Test-Path $tempPath) {
        $files = Get-ChildItem -Path $tempPath -Recurse -File -ErrorAction SilentlyContinue
        foreach ($file in $files) {
            try {
                $totalSize += $file.Length
                Remove-Item -Path $file.FullName -Force -Confirm:$false -ErrorAction Stop
                $totalRemoved++
            } catch {
                # Kullanımda olan dosyalar atlanır
            }
        }
        # Bos klasorleri temizle
        Get-ChildItem -Path $tempPath -Recurse -Directory -ErrorAction SilentlyContinue |
            Where-Object { (Get-ChildItem $_.FullName -ErrorAction SilentlyContinue).Count -eq 0 } |
            ForEach-Object { Remove-Item $_.FullName -Force -Recurse -Confirm:$false -ErrorAction SilentlyContinue }
    }
}

$sizeMB = [math]::Round($totalSize / 1MB, 2)
Write-Output "Temizlenen dosya sayisi: $totalRemoved"
Write-Output "Kazanilan alan: $sizeMB MB"
Write-Output "Islem tamamlandi."
