from __future__ import annotations

import unittest
from pathlib import Path

import experiment_web.app as web


READY = {
    "connected": True,
    "control_api": True,
    "session_started": True,
    "ads1299_selected": True,
    "ads1299_connected": True,
    "streaming": False,
    "recording": False,
    "ready": True,
    "message": "ready",
}


class FakeController:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.started: list[tuple[str, str]] = []
        self.stop_count = 0

    def status(self):
        status = dict(READY)
        if not self.ready:
            status.update(ready=False, ads1299_connected=False, message="board missing")
        return status

    def start_stage(self, recording_session: str, stage: str):
        self.started.append((recording_session, stage))
        return {"ok": True, "message": "started", "file_base": f"{recording_session}_{stage}"}

    def stop(self):
        self.stop_count += 1
        return {"ok": True, "message": "saved"}


class WebApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(__file__).resolve().parent
        self.old_data_dir = web.EXPERIMENT_CONFIG["data_dir"]
        self.old_gui = web.gui
        web.EXPERIMENT_CONFIG["data_dir"] = str(self.temp_dir)
        web.gui = FakeController()
        web._log_path = None
        web._recording_session = None
        web._active_stage = None
        self.client = web.app.test_client()

    def tearDown(self) -> None:
        web.EXPERIMENT_CONFIG["data_dir"] = self.old_data_dir
        web.gui = self.old_gui

    def test_experiment_start_is_blocked_until_ads1299_is_connected(self) -> None:
        web.gui = FakeController(ready=False)
        response = self.client.post(
            "/api/experiment/start", json={"subject_id": "SUB01", "session": "01"}
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["status"], "device_not_ready")

    def test_safe_session_and_stage_suffix_are_used(self) -> None:
        response = self.client.post(
            "/api/experiment/start",
            json={"subject_id": "../SUB/01", "session": "01"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertNotIn("/", payload["recording_session"])
        self.assertEqual(Path(payload["csv_path"]).parent, self.temp_dir)

        stage_response = self.client.post(
            "/api/gui/start_stage", json={"stage_name": "eyes_open"}
        )
        self.assertEqual(stage_response.status_code, 200)
        recording_session, stage = web.gui.started[0]
        self.assertEqual(stage, "eyes_open")
        self.assertTrue(f"{recording_session}_{stage}".endswith("_eyes_open"))

        stop_response = self.client.post("/api/gui/stop")
        self.assertEqual(stop_response.status_code, 200)
        self.assertEqual(web.gui.stop_count, 1)

    def test_unknown_stage_is_rejected(self) -> None:
        self.client.post(
            "/api/experiment/start", json={"subject_id": "SUB01", "session": "01"}
        )
        response = self.client.post(
            "/api/gui/start_stage", json={"stage_name": "../../escape"}
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
