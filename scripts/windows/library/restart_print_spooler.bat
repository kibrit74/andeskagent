@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0..\run-library-script.ps1" -ScriptName "restart_print_spooler"
exit /b %ERRORLEVEL%
