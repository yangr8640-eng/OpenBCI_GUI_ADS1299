@echo off
REM Run the MIST EEG Experiment (Web Version)
REM Start the Flask server, then open http://localhost:8080 in your browser.
REM Prerequisites: Python 3.10+ installed
REM Start OpenBCI GUI first for automatic recording.

cd /d "%~dp0"

netstat -ano | findstr ":8080" | findstr "LISTENING" >nul
if not errorlevel 1 (
    powershell -NoProfile -Command "try { $s = Invoke-RestMethod http://127.0.0.1:8080/api/gui/status -TimeoutSec 2; if ($null -ne $s.control_api) { exit 0 } } catch {}; exit 1"
    if not errorlevel 1 (
        echo MIST web server is already running. Opening the current page...
        start "" "http://localhost:8080/?v=20260714-2"
        exit /b 0
    )
    echo.
    echo ERROR: Port 8080 is already in use by an older experiment server.
    echo Close the old MIST web-server window, then run this script again.
    echo.
    pause
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    python -m venv venv
    call venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate
)

echo.
echo Starting MIST EEG Experiment Web Server...
echo Open http://localhost:8080 in your browser.
echo.
start http://localhost:8080
python app.py
pause
