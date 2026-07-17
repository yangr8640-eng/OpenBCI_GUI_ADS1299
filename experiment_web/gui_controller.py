"""Reliable TCP client for the OpenBCI GUI experiment-control service.

The GUI protocol is newline-delimited text:

``PING``
    Confirms that the experiment-control service is running.
``STATUS``
    Returns GUI, ADS1299, streaming, and recording state.
``RECORD:<session>|<file-base-name>``
    Starts one stage.  The file base name does not include ``.txt``.
``STOP``
    Stops streaming and closes the current recording before replying.
"""

from __future__ import annotations

import socket
import threading
from typing import Any


def _false_status(message: str) -> dict[str, Any]:
    return {
        "connected": False,
        "control_api": False,
        "session_started": False,
        "ads1299_selected": False,
        "ads1299_connected": False,
        "streaming": False,
        "recording": False,
        "ready": False,
        "message": message,
    }


class GUIController:
    """Send serialized recording-control commands to the OpenBCI GUI."""

    def __init__(self, host: str = "127.0.0.1", port: int = 1236, timeout: float = 3.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None
        self._lock = threading.RLock()

    def connect(self) -> bool:
        """Connect (or reconnect) and verify the GUI control service."""
        with self._lock:
            if self.sock is not None:
                return True
            try:
                self.sock = socket.create_connection(
                    (self.host, self.port), timeout=self.timeout
                )
                self.sock.settimeout(self.timeout)
                response = self._send_on_socket("PING")
                if response == "PONG":
                    return True
            except (ConnectionRefusedError, socket.timeout, OSError) as exc:
                print(
                    f"[GUIController] Cannot connect to GUI at "
                    f"{self.host}:{self.port}: {exc}"
                )
            self._disconnect_locked()
            return False

    def disconnect(self) -> None:
        """Close the control connection."""
        with self._lock:
            self._disconnect_locked()

    def _disconnect_locked(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def _send_on_socket(self, command: str) -> str:
        if self.sock is None:
            raise ConnectionError("GUI control socket is not connected")
        self.sock.sendall((command + "\n").encode("utf-8"))
        response = self._recv_line()
        if not response:
            raise ConnectionError("GUI closed the control connection")
        print(f"[GUIController] {command!r} -> {response!r}")
        return response

    def _request(self, command: str, *, retry_safe: bool = False) -> str | None:
        """Send one command; reconnect once only for idempotent commands."""
        attempts = 2 if retry_safe else 1
        with self._lock:
            for _ in range(attempts):
                if self.sock is None and not self.connect():
                    continue
                try:
                    return self._send_on_socket(command)
                except (ConnectionError, socket.timeout, OSError) as exc:
                    print(f"[GUIController] Command {command!r} failed: {exc}")
                    self._disconnect_locked()
            return None

    def _recv_line(self) -> str:
        if self.sock is None:
            raise ConnectionError("GUI control socket is not connected")
        data = bytearray()
        while len(data) < 8192:
            chunk = self.sock.recv(1)
            if not chunk:
                break
            if chunk == b"\n":
                break
            if chunk != b"\r":
                data.extend(chunk)
        return data.decode("utf-8", errors="replace")

    def status(self) -> dict[str, Any]:
        """Return live GUI and ADS1299 readiness state."""
        response = self._request("STATUS", retry_safe=True)
        if response is None:
            return _false_status("OpenBCI GUI 未打开或控制端口不可达")
        if not response.startswith("STATUS|"):
            status = _false_status("GUI 版本不包含完整的实验控制接口，请重新构建 GUI")
            status["connected"] = True
            return status

        values: dict[str, str] = {}
        for item in response.split("|")[1:]:
            key, separator, value = item.partition("=")
            if separator:
                values[key] = value

        status: dict[str, Any] = {
            "connected": True,
            "control_api": True,
            "session_started": values.get("session_started") == "1",
            "ads1299_selected": values.get("ads1299_selected") == "1",
            "ads1299_connected": values.get("ads1299_connected") == "1",
            "streaming": values.get("streaming") == "1",
            "recording": values.get("recording") == "1",
        }
        status["ready"] = all(
            status[key]
            for key in (
                "connected",
                "control_api",
                "session_started",
                "ads1299_selected",
                "ads1299_connected",
            )
        ) and not status["streaming"] and not status["recording"]

        if not status["session_started"]:
            status["message"] = "请在 GUI 中选择 ADS1299 数据源并点击 START SESSION"
        elif not status["ads1299_selected"]:
            status["message"] = "GUI 当前数据源不是 ADS1299 16CH WIFI TCP"
        elif not status["ads1299_connected"]:
            status["message"] = "GUI 已就绪，正在等待 ADS1299 硬件连接"
        elif status["streaming"] or status["recording"]:
            status["message"] = "GUI 当前仍在采集，请先停止已有采集"
        else:
            status["message"] = "GUI 与 ADS1299 均已就绪"
        return status

    def start_stage(self, recording_session: str, stage_name: str) -> dict[str, Any]:
        """Start one stage and return the GUI's explicit acknowledgement."""
        file_base = f"{recording_session}_{stage_name}"
        response = self._request(f"RECORD:{recording_session}|{file_base}")
        if response is None:
            return {"ok": False, "message": "无法连接 GUI 或未收到启动确认"}
        if response.startswith("OK:RECORDING"):
            return {
                "ok": True,
                "message": "采集已开始",
                "file_base": file_base,
                "response": response,
            }
        return {"ok": False, "message": response, "response": response}

    def stop(self) -> dict[str, Any]:
        """Stop streaming and wait until the GUI confirms the file is closed."""
        response = self._request("STOP", retry_safe=True)
        if response is None:
            return {"ok": False, "message": "无法连接 GUI 或未收到保存确认"}
        if response.startswith("OK:STOPPED"):
            return {"ok": True, "message": "采集已停止，文件已保存", "response": response}
        return {"ok": False, "message": response, "response": response}

    def ping(self) -> bool:
        return self._request("PING", retry_safe=True) == "PONG"
