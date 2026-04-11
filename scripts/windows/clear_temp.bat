@echo off
echo Temp dosyalari temizleniyor...
powershell -ExecutionPolicy Bypass -File "%~dp0clear_temp.ps1"
pause
