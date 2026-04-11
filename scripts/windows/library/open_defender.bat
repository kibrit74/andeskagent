@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0..\run-library-script.ps1" -ScriptName "open_defender"
exit /b %ERRORLEVEL%
