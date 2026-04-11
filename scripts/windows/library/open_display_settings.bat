@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0..\run-library-script.ps1" -ScriptName "open_display_settings"
exit /b %ERRORLEVEL%
