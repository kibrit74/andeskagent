@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0..\run-library-script.ps1" -ScriptName "capture_screenshot"
exit /b %ERRORLEVEL%
