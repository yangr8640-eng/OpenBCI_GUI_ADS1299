"""MIST EEG experiment web server and OpenBCI GUI control proxy."""

from __future__ import annotations

import csv
import os
import re
import socket
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

try:
    from .gui_controller import GUIController
except ImportError:  # Running directly with ``python app.py``.
    from gui_controller import GUIController


GUI_CONTROL_ENABLED = os.environ.get("MIST_GUI_CONTROL", "1") != "0"
GUI_CONTROL_HOST = os.environ.get("MIST_GUI_HOST", "127.0.0.1")
GUI_CONTROL_PORT = int(os.environ.get("MIST_GUI_PORT", "1236"))

gui: GUIController | None = (
    GUIController(GUI_CONTROL_HOST, GUI_CONTROL_PORT) if GUI_CONTROL_ENABLED else None
)

app = Flask(__name__)
WEB_HOST = "127.0.0.1"
WEB_PORT = int(os.environ.get("MIST_WEB_PORT", "8080"))

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

STAGE_NAMES = {
    "eyes_open",
    "eyes_closed",
    "practice",
    "control",
    "stress",
    "recovery",
}

FIELDNAMES = [
    "row_type", "stage", "condition", "event", "trial_index",
    "problem", "a", "b", "operator", "true_value", "shown_value",
    "equation_is_true", "correct_key", "response", "rt", "correct",
    "timeout", "deadline", "feedback_type", "problem_onset",
    "response_time", "feedback_onset", "time_global", "duration",
    "vas_rating", "current_performance", "peer_average",
    "target_performance", "condition_order", "practice_accuracy",
    "control_accuracy", "stress_initial_deadline", "skipped",
    "participant_age", "participant_sex", "participant_handedness",
    "experimenter_id",
]

_log_path: Path | None = None
_recording_session: str | None = None
_active_stage: str | None = None
_csv_lock = threading.Lock()
_state_lock = threading.RLock()


def _now_string() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_component(value: Any, fallback: str, max_length: int = 48) -> str:
    """Make participant-provided text safe for a file or folder name."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("._-")[:max_length]
    return cleaned or fallback


def _write_csv_row(row: dict[str, Any]) -> None:
    if _log_path is None:
        return
    with _csv_lock:
        _log_path.parent.mkdir(parents=True, exist_ok=True)
        exists = _log_path.exists()
        with _log_path.open("a", newline="", encoding="utf-8-sig") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
            if not exists:
                writer.writeheader()
            writer.writerow({name: row.get(name, "") for name in FIELDNAMES})


def _gui_status() -> dict[str, Any]:
    if gui is None:
        return {
            "connected": False,
            "control_api": False,
            "session_started": False,
            "ads1299_selected": False,
            "ads1299_connected": False,
            "streaming": False,
            "recording": False,
            "ready": False,
            "message": "GUI 自动控制已禁用",
        }
    return gui.status()


@app.route("/")
def index():
    return render_template("index.html")


@app.after_request
def disable_experiment_page_caching(response):
    """Avoid mixing cached HTML with a newly updated experiment script."""
    if request.path == "/" or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.route("/api/experiment/config")
def get_config():
    return jsonify(EXPERIMENT_CONFIG)


@app.route("/api/experiment/start", methods=["POST"])
def start_experiment():
    """Create a behavior log only after GUI and ADS1299 are ready."""
    global _log_path, _recording_session, _active_stage

    status = _gui_status()
    if not status["ready"]:
        return jsonify({"status": "device_not_ready", "gui": status}), 409

    data = request.get_json(silent=True) or {}
    subject_id = _safe_component(data.get("subject_id"), "TEST")
    session = _safe_component(data.get("session"), "01", 12)
    stamp = _now_string()

    with _state_lock:
        _recording_session = f"MIST_{subject_id}_ses-{session}_{stamp}"
        _active_stage = None
        data_dir = Path(EXPERIMENT_CONFIG["data_dir"])
        data_dir.mkdir(parents=True, exist_ok=True)
        _log_path = data_dir / f"{_recording_session}.csv"

    print(f"[CSV] Logging to: {_log_path}")
    return jsonify(
        {
            "status": "ok",
            "csv_path": str(_log_path),
            "recording_session": _recording_session,
            "subject_id": subject_id,
            "session": session,
        }
    )


@app.route("/api/log", methods=["POST"])
def log_event():
    data = request.get_json(silent=True) or {}
    data["time_global"] = data.get("time_global", datetime.now().isoformat())
    _write_csv_row(data)
    return jsonify({"status": "ok"})


@app.route("/api/gui/start_stage", methods=["POST"])
def gui_start_stage():
    """Start streaming and open a uniquely named file for one stage."""
    global _active_stage
    if gui is None:
        return jsonify({"status": "gui_unavailable", "message": "GUI 控制已禁用"}), 503

    data = request.get_json(silent=True) or {}
    stage_name = str(data.get("stage_name", ""))
    if stage_name not in STAGE_NAMES:
        return jsonify({"status": "invalid_stage", "message": "未知实验阶段"}), 400

    with _state_lock:
        if _recording_session is None:
            return jsonify({"status": "experiment_not_started"}), 409

        live = _gui_status()
        if _active_stage == stage_name and live["streaming"] and live["recording"]:
            return jsonify({"status": "ok", "already_active": True})
        if not live["ready"]:
            return jsonify({"status": "device_not_ready", "gui": live}), 409

        result = gui.start_stage(_recording_session, stage_name)
        if result["ok"]:
            _active_stage = stage_name
            return jsonify({"status": "ok", **result})
        return jsonify({"status": "failed", **result}), 502


@app.route("/api/gui/stop", methods=["POST"])
def gui_stop():
    """Stop streaming; success means the GUI has closed the stage file."""
    global _active_stage
    if gui is None:
        return jsonify({"status": "gui_unavailable", "message": "GUI 控制已禁用"}), 503
    with _state_lock:
        result = gui.stop()
        if result["ok"]:
            stopped_stage = _active_stage
            _active_stage = None
            return jsonify({"status": "ok", "stage": stopped_stage, **result})
        return jsonify({"status": "failed", **result}), 502


@app.route("/api/gui/status")
def gui_status():
    status = _gui_status()
    status["active_stage"] = _active_stage
    return jsonify(status)


if __name__ == "__main__":
    os.chdir(str(Path(__file__).resolve().parent))
    print("=" * 60)
    print("  MIST EEG Experiment — Web Server")
    print("=" * 60)
    print(f"  GUI control: {GUI_CONTROL_HOST}:{GUI_CONTROL_PORT}")
    print(f"  Data dir:    {EXPERIMENT_CONFIG['data_dir']}")
    print(f"  Open http://localhost:{WEB_PORT} in your browser.")
    print("=" * 60)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        if probe.connect_ex((WEB_HOST, WEB_PORT)) == 0:
            print()
            print(f"ERROR: {WEB_HOST}:{WEB_PORT} is already in use.")
            print("Close the old MIST web-server window before starting a new one.")
            sys.exit(1)
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False, threaded=True)
