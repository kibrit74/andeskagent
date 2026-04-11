@echo off
echo Outlook onarimi baslatiliyor...
powershell -ExecutionPolicy Bypass -File "%~dp0outlook_repair.ps1"
pause
