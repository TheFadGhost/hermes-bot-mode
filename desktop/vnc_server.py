"""Own the VNC child independently of X/Chromium and replace it on handoff.

x11vnc's X-property remote control can block behind a slow framebuffer client.
This local control socket remains responsive even when that child is blocked.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

SOCKET = "/tmp/bot-vnc-control.sock"


class VNCServer:
    def __init__(self, port=5900):
        self.port = port
        self.child = None

    def stop(self):
        child, self.child = self.child, None
        if child is None:
            return
        child.terminate()
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=2)

    def change(self, mode):
        if mode not in {"bot", "manual"}:
            raise ValueError("Invalid computer control mode")
        # Old sockets must be gone before an interactive replacement starts.
        self.stop()
        args = ["x11vnc", "-display", ":99", "-forever", "-shared",
                "-nopw", "-localhost", "-rfbport", str(self.port), "-quiet"]
        if mode == "bot":
            args.append("-viewonly")
        self.child = subprocess.Popen(args)
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if self.child.poll() is not None:
                    raise RuntimeError("Computer viewer exited during startup")
                try:
                    with socket.create_connection(("127.0.0.1", self.port), .25) as client:
                        client.settimeout(.25)
                        if client.recv(12).startswith(b"RFB "):
                            return
                except OSError:
                    pass
                time.sleep(.1)
            raise RuntimeError("Computer viewer did not become ready")
        except BaseException:
            self.stop()
            raise


def serve(path=SOCKET, port=5900):
    server = VNCServer(port)
    def shutdown(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    Path(path).unlink(missing_ok=True)
    try:
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(path)
            os.chmod(path, 0o600)
            listener.listen(2)
            listener.settimeout(1)
            # Publish the control listener before RFB becomes visible. A
            # handoff arriving during initial startup queues until it is ready.
            server.change("bot")
            while True:
                if server.child is None or server.child.poll() is not None:
                    raise RuntimeError("Computer viewer exited unexpectedly")
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                with connection:
                    connection.settimeout(12)
                    try:
                        mode = connection.recv(32).decode().strip()
                        server.change(mode)
                        result = {"ok": True}
                    except Exception as exc:
                        result = {"ok": False, "error": str(exc)}
                    try:
                        connection.sendall(json.dumps(result).encode())
                    except OSError:
                        pass
    finally:
        server.stop()
        Path(path).unlink(missing_ok=True)


def control(mode, path=SOCKET):
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(12)
        deadline = time.monotonic() + 3
        while True:
            try:
                connection.connect(path)
                break
            except (FileNotFoundError, ConnectionRefusedError) as exc:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Computer control is not ready; retry opening the computer") from exc
                time.sleep(.05)
        connection.sendall(mode.encode())
        chunks = []
        while chunk := connection.recv(1024):
            chunks.append(chunk)
        result = json.loads(b"".join(chunks))
    if not result.get("ok"):
        raise RuntimeError(result.get("error", "Computer handoff failed"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "bot", "manual"])
    parser.add_argument("--socket", default=SOCKET)
    parser.add_argument("--port", type=int, default=5900)
    options = parser.parse_args()
    if options.command == "serve":
        serve(options.socket, options.port)
    else:
        control(options.command, options.socket)

