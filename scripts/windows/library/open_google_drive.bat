@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0..\run-library-script.ps1" -ScriptName "open_google_drive"
exit /b %ERRORLEVEL%
