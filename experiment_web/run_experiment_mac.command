#!/bin/bash
# Run the MIST EEG Experiment (Web Version)
# Start the Flask server, then open http://localhost:5000 in your browser.
# Start OpenBCI GUI first for automatic recording.

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

echo "Starting MIST EEG Experiment Web Server..."
echo "Open http://localhost:8080 in your browser."
echo ""

open http://localhost:8080 2>/dev/null &
python app.py
