from __future__ import annotations

import socket
import threading
import unittest

from experiment_web.gui_controller import GUIController


class FakeGuiServer:
    def __init__(self) -> None:
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen()
        self.port = self.server.getsockname()[1]
        self.commands: list[str] = []
        self.running = True
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while self.running:
            try:
                client, _ = self.server.accept()
            except OSError:
                return
            with client, client.makefile("r", encoding="utf-8") as reader:
                for raw_line in reader:
                    command = raw_line.strip()
                    self.commands.append(command)
                    if command == "PING":
                        response = "PONG"
                    elif command == "STATUS":
                        response = (
                            "STATUS|session_started=1|ads1299_selected=1"
                            "|ads1299_connected=1|streaming=0|recording=0"
                        )
                    elif command.startswith("RECORD:"):
                        response = "OK:RECORDING test"
                    elif command == "STOP":
                        response = "OK:STOPPED"
                    else:
                        response = "ERR:unknown"
                    client.sendall((response + "\n").encode("utf-8"))

    def close(self) -> None:
        self.running = False
        self.server.close()
        try:
            socket.create_connection(("127.0.0.1", self.port), timeout=0.1).close()
        except OSError:
            pass
        self.thread.join(timeout=1)


class GUIControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeGuiServer()
        self.controller = GUIController(port=self.server.port, timeout=0.5)

    def tearDown(self) -> None:
        self.controller.disconnect()
        self.server.close()

    def test_live_status_requires_all_ads1299_readiness_flags(self) -> None:
        status = self.controller.status()
        self.assertTrue(status["connected"])
        self.assertTrue(status["control_api"])
        self.assertTrue(status["ads1299_connected"])
        self.assertTrue(status["ready"])

    def test_stage_filename_ends_with_stage_name(self) -> None:
        result = self.controller.start_stage(
            "MIST_SUB01_ses-01_20260714_120000", "eyes_open"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(
            result["file_base"],
            "MIST_SUB01_ses-01_20260714_120000_eyes_open",
        )
        self.assertIn(
            "RECORD:MIST_SUB01_ses-01_20260714_120000|"
            "MIST_SUB01_ses-01_20260714_120000_eyes_open",
            self.server.commands,
        )

    def test_stop_waits_for_gui_acknowledgement(self) -> None:
        self.assertTrue(self.controller.stop()["ok"])
        self.assertIn("STOP", self.server.commands)


if __name__ == "__main__":
    unittest.main()
