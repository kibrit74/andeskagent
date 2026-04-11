@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_CMD="
where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set "PYTHON_CMD=python"
    )
)

if not defined PYTHON_CMD (
    echo [HATA] Python bulunamadi. Python 3.11+ kurup tekrar deneyin.
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [INFO] .venv olusturuluyor...
    call %PYTHON_CMD% -m venv .venv
    if errorlevel 1 exit /b 1
)

echo [INFO] Bagimliliklar kuruluyor/guncelleniyor...
call .venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo [INFO] Sunucu baslatiliyor: http://127.0.0.1:8000
call .venv\Scripts\python.exe -m uvicorn server.main:app --reload

endlocal
