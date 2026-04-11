@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0..\run-library-script.ps1" -ScriptName "open_bluetooth_settings"
exit /b %ERRORLEVEL%
