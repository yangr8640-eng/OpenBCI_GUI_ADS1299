"""
TCP client to control the OpenBCI GUI recording from the MIST experiment.

Usage:
    from gui_controller import GUIController

    gui = GUIController()
    if gui.connect():
        gui.start_stage("SUB01", "eyes_open")   # starts recording
        # ... stage runs for 3 minutes ...
        gui.stop()                               # stops recording
        gui.disconnect()

The GUI must be running and in POSTINIT mode (session started) before
connecting. Commands are:

    RECORD:<name>  -- stop current recording, set name, start new recording
    STOP           -- stop current recording
    PING           -- test connection, returns "PONG"
"""

import socket
import time


class GUIController:
    """Send recording control commands to the OpenBCI GUI via TCP."""

    def __init__(self, host: str = "127.0.0.1", port: int = 1236, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: socket.socket | None = None

    def connect(self) -> bool:
        """
        Connect to the GUI's experiment control server.

        Returns True on success, False if the GUI is not reachable.
        """
        try:
            self.sock = socket.create_connection(
                (self.host, self.port), timeout=self.timeout
            )
            # Verify with ping
            if self.ping():
                return True
            else:
                self.disconnect()
                return False
        except (ConnectionRefusedError, socket.timeout, OSError) as exc:
            print(f"[GUIController] Cannot connect to GUI at {self.host}:{self.port}: {exc}")
            return False

    def disconnect(self) -> None:
        """Close the TCP connection to the GUI."""
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
            print("[GUIController] Disconnected from GUI")

    def _send(self, cmd: str) -> str | None:
        """
        Send a command to the GUI and return the response line.

        Returns the response string or None on failure.
        """
        if self.sock is None:
            print("[GUIController] Not connected — cannot send command")
            return None
        try:
            self.sock.sendall((cmd + "\n").encode("utf-8"))
            # Read response (single line)
            response = self._recv_line()
            print(f"[GUIController] Sent: {cmd!r}  →  Response: {response!r}")
            return response
        except OSError as exc:
            print(f"[GUIController] Failed to send command {cmd!r}: {exc}")
            self.disconnect()
            return None

    def _recv_line(self) -> str:
        """Read a single newline-terminated line from the socket."""
        buf = b""
        while True:
            chunk = self.sock.recv(1)
            if not chunk:
                break
            if chunk == b"\n":
                break
            buf += chunk
        return buf.decode("utf-8", errors="replace")

    def start_stage(self, subject_id: str, stage_name: str) -> bool:
        """
        Start recording for a stage.

        The recording file will be named: {subject_id}-{stage_name}-RAW.txt

        Returns True if the command was accepted.
        """
        name = f"{subject_id}-{stage_name}-RAW"
        response = self._send(f"RECORD:{name}")
        return response is not None and response.startswith("OK")

    def stop(self) -> bool:
        """
        Stop the current recording.

        Returns True if the command was accepted.
        """
        response = self._send("STOP")
        return response is not None and response.startswith("OK")

    def ping(self) -> bool:
        """
        Test the connection to the GUI.

        Returns True if the GUI responds with PONG.
        """
        response = self._send("PING")
        return response is not None and "PONG" in response
