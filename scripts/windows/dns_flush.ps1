# dns_flush.ps1 — DNS onbellegini temizle ve kontrol et

Write-Output "DNS onbellegi temizleniyor..."

try {
    ipconfig /flushdns
    Write-Output ""
    Write-Output "DNS onbellegi basariyla temizlendi."
} catch {
    Write-Output "DNS temizleme sirasinda hata olustu: $_"
}

# Mevcut DNS yapilandirmasini goster
Write-Output ""
Write-Output "--- Mevcut DNS Yapilandirmasi ---"
Get-DnsClientServerAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.ServerAddresses.Count -gt 0 } |
    Format-Table InterfaceAlias, ServerAddresses -AutoSize

Write-Output "Islem tamamlandi."
