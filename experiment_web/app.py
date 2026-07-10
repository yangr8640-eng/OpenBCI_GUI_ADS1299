"""
MIST EEG Experiment — Web Backend (Flask)

Serves the experiment page and provides REST endpoints for:
- CSV trial logging
- OpenBCI GUI recording control (via TCP proxy)
- Experiment configuration

Usage:
    pip install flask
    python app.py
    # Open http://localhost:5000 in a browser
"""

from __future__ import annotations

import csv
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

# ---- GUI Integration ----
GUI_CONTROL_ENABLED = True
GUI_CONTROL_HOST = "127.0.0.1"
GUI_CONTROL_PORT = 1236

gui: Any = None
if GUI_CONTROL_ENABLED:
    try:
        from gui_controller import GUIController

        gui = GUIController(GUI_CONTROL_HOST, GUI_CONTROL_PORT)
        if gui.connect():
            print(f"[GUI] Connected to OpenBCI GUI at {GUI_CONTROL_HOST}:{GUI_CONTROL_PORT}")
        else:
            print("[GUI] WARNING: Could not connect to OpenBCI GUI. Recording will NOT be automatic.")
            print("[GUI]   Make sure the GUI is running and a SESSION has been started.")
            gui = None
    except Exception as exc:
        print(f"[GUI] Control disabled: {exc}")
        gui = None

# ---- Flask App ----
app = Flask(__name__)

# ---- Experiment Config ----
EXPERIMENT_CONFIG: dict[str, Any] = {
    "data_dir": str(Path.home() / "Desktop" / "MIST_data"),
    "eyes_open_sec": 180.0,
    "eyes_closed_sec": 180.0,
    "practice_sec": 180.0,
    "control_sec": 180.0,
    "stress_sec": 180.0,
    "recovery_sec": 180.0,
    "fixation_sec": 0.35,
    "feedback_sec": 0.85,
    "iti_min": 0.25,
    "iti_max": 0.55,
    "practice_deadline": 8.0,
    "control_deadline": 10.0,
    "stress_deadline_start": 3.2,
    "stress_deadline_min": 1.1,
    "stress_deadline_max": 4.5,
    "stress_target_boost": 15,
    "stress_target_min": 75,
    "stress_target_max": 95,
    "peer_boost": 8,
    "target_success_rate": 0.55,
    "show_deadline_seconds": False,
}

# Log file state — set when experiment starts
_log_path: Path | None = None
_fieldnames: list[str] = []

FIELDNAMES = [
    "row_type", "stage", "condition", "event", "trial_index",
    "problem", "a", "b", "operator", "true_value", "shown_value",
    "equation_is_true", "correct_key", "response", "rt", "correct",
    "timeout", "deadline", "feedback_type", "problem_onset",
    "response_time", "feedback_onset", "time_global", "duration",
    "vas_rating", "current_performance", "peer_average",
    "target_performance", "condition_order", "practice_accuracy",
    "control_accuracy", "stress_initial_deadline", "skipped",
]


def _now_string() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _write_csv_row(row: dict[str, Any]) -> None:
    """Append a row to the experiment CSV log."""
    global _log_path
    if _log_path is None:
        return
    _log_path.parent.mkdir(parents=True, exist_ok=True)
    exists = _log_path.exists()
    with _log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not exists:
            writer.writeheader()
        writer.writerow({name: row.get(name, "") for name in FIELDNAMES})


# ---- Routes ----


@app.route("/")
def index():
    """Serve the experiment page."""
    return render_template("index.html")


@app.route("/api/experiment/config")
def get_config():
    """Return experiment configuration to the frontend."""
    return jsonify({**EXPERIMENT_CONFIG, "gui_connected": gui is not None})


@app.route("/api/experiment/start", methods=["POST"])
def start_experiment():
    """Initialize the CSV log file for a new experiment session."""
    global _log_path
    data = request.get_json() or {}
    subject_id = data.get("subject_id", "TEST")
    session = data.get("session", "01")

    data_dir = Path(EXPERIMENT_CONFIG["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    _log_path = data_dir / f"MIST_{subject_id}_ses-{session}_{_now_string()}.csv"

    print(f"[CSV] Logging to: {_log_path}")
    return jsonify({"status": "ok", "csv_path": str(_log_path)})


@app.route("/api/log", methods=["POST"])
def log_event():
    """Receive a trial/block/experiment event and write it to CSV."""
    data = request.get_json() or {}
    data["time_global"] = data.get("time_global", datetime.now().isoformat())
    _write_csv_row(data)
    return jsonify({"status": "ok"})


@app.route("/api/gui/start_stage", methods=["POST"])
def gui_start_stage():
    """Tell the GUI to start recording for a stage."""
    global gui
    if gui is None:
        return jsonify({"status": "gui_unavailable"})
    data = request.get_json() or {}
    subject_id = data.get("subject_id", "TEST")
    stage_name = data.get("stage_name", "unknown")
    try:
        ok = gui.start_stage(subject_id, stage_name)
        return jsonify({"status": "ok" if ok else "failed"})
    except Exception as exc:
        print(f"[GUI] start_stage error: {exc}")
        return jsonify({"status": "error", "message": str(exc)})


@app.route("/api/gui/stop", methods=["POST"])
def gui_stop():
    """Tell the GUI to stop recording."""
    global gui
    if gui is None:
        return jsonify({"status": "gui_unavailable"})
    try:
        ok = gui.stop()
        return jsonify({"status": "ok" if ok else "failed"})
    except Exception as exc:
        print(f"[GUI] stop error: {exc}")
        return jsonify({"status": "error", "message": str(exc)})


@app.route("/api/gui/status")
def gui_status():
    """Check whether the GUI is connected."""
    return jsonify({"connected": gui is not None})


# ---- Main ----

if __name__ == "__main__":
    os.chdir(str(Path(__file__).resolve().parent))
    print("=" * 60)
    print("  MIST EEG Experiment — Web Server")
    print("=" * 60)
    print()
    print(f"  GUI Control: {'CONNECTED' if gui else 'NOT CONNECTED'}")
    print(f"  Data Dir:    {EXPERIMENT_CONFIG['data_dir']}")
    print()
    print("  Open http://localhost:5000 in your browser to start.")
    print("  Press Ctrl+C to stop the server.")
    print()
    app.run(host="127.0.0.1", port=5000, debug=False)
