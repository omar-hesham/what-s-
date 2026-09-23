@echo off
title Omar WhatsApp Intelligence (OWI)
cd /d "%~dp0"

echo ========================================================
echo  Starting Omar WhatsApp Intelligence (OWI)
echo  100%% Local-First - Zero Recurring Costs - Privacy-Safe
echo ========================================================
echo.

if not exist "backend\.venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at backend\.venv\Scripts\python.exe
    echo Please run uv venv backend\.venv to initialize.
    pause
    exit /b 1
)

:: Check if port 8765 is already listening
netstat -ano | findstr /R /C:":8765 .*LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [INFO] OWI service is already running on port 8765!
    echo Opening browser interface at http://127.0.0.1:8765 ...
    start "" http://127.0.0.1:8765
    exit /b 0
)

echo [1/2] Opening browser interface on http://127.0.0.1:8765 ...
start "" http://127.0.0.1:8765

echo [2/2] Running OWI service (Press Ctrl+C to stop)...
backend\.venv\Scripts\python.exe backend\run_backend.py

pause
