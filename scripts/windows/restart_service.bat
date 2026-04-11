@echo off
echo Servis yeniden baslatiliyor...
powershell -ExecutionPolicy Bypass -File "%~dp0restart_service.ps1"
pause
