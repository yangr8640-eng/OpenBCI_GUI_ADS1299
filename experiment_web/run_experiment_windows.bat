@echo off
REM Run the MIST EEG Experiment (Web Version)
REM Start the Flask server, then open http://localhost:8080 in your browser.
REM Prerequisites: Python 3.10+ installed
REM Start OpenBCI GUI first for automatic recording.

cd /d "%~dp0"

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
