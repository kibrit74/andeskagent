@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0..\run-library-script.ps1" -ScriptName "close_onedrive"
exit /b %ERRORLEVEL%
