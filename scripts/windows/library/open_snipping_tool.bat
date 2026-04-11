@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0..\run-library-script.ps1" -ScriptName "open_snipping_tool"
exit /b %ERRORLEVEL%
