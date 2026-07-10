@echo off
REM Run the MIST EEG Experiment on Windows
REM Prerequisites:
REM   1. Install Python 3.10+: https://www.python.org/downloads/
REM   2. Create venv:    python -m venv venv
REM   3. Activate venv:  venv\Scripts\activate
REM   4. Install deps:   pip install -r experiment\requirements.txt
REM   5. Start OpenBCI GUI first, then run this script

cd /d "%~dp0.."
venv\Scripts\python -m experiment.mist
pause
