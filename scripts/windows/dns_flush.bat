@echo off
echo DNS cache temizleniyor...
powershell -ExecutionPolicy Bypass -File "%~dp0dns_flush.ps1"
pause
