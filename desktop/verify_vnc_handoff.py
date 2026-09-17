"""Run inside an awake QA desktop: exercises a separate VNC port, not Chromium.

python3 verify_vnc_handoff.py /path/to/vnc_server.py
The control channel must remain responsive while a full-frame viewer stops
reading. Fresh connections must still deliver pixels and enforce input policy.
"""
import json
import socket
import struct
import subprocess
import sys
import time

PORT = 5901
CONTROL = "/tmp/verify-vnc-handoff.sock"


def read(client, length):
    result = b""
    while len(result) < length:
        part = client.recv(length - len(result))
        assert part, "VNC closed before completing a frame"
        result += part
    return result


def viewer(slow=False):
    client = socket.socket()
    client.settimeout(3)
    if slow:
        client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
    client.connect(("127.0.0.1", PORT))
    assert read(client, 12).startswith(b"RFB ")
    client.sendall(b"RFB 003.008\n")
    choices = read(client, read(client, 1)[0])
    assert 1 in choices
    client.sendall(b"\x01")
    assert read(client, 4) == b"\0\0\0\0"
    client.sendall(b"\x01")
    header = read(client, 24)
    read(client, struct.unpack("!I", header[20:24])[0])
    return client, struct.unpack("!HH", header[:4]), header[4] // 8


def position():
    output = subprocess.check_output(["xdotool", "getmouselocation", "--shell"], text=True)
    values = dict(line.split("=", 1) for line in output.splitlines())
    return int(values["X"]), int(values["Y"])


def main():
    manager = subprocess.Popen(["python3", sys.argv[1], "serve", "--port", str(PORT), "--socket", CONTROL])
    try:
        for _ in range(100):
            try:
                with socket.socket(socket.AF_UNIX) as probe:
                    probe.connect(CONTROL)
                    probe.sendall(b"bot")
                    assert json.loads(probe.recv(1024))["ok"]
                break
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(.1)
        else:
            raise AssertionError("VNC control did not start")
        subprocess.run(["xdotool", "mousemove", "66", "77"], check=True)
        expected = (66, 77)
        for mode in ["manual", "bot", "manual", "bot"]:
            blocked, (width, height), _ = viewer(slow=True)
            try:
                blocked.sendall(struct.pack("!BBHHHH", 3, 0, 0, 0, width, height))
                time.sleep(.4)  # Force output backpressure before handoff.
                started = time.monotonic()
                subprocess.run(["python3", sys.argv[1], mode, "--socket", CONTROL], check=True, timeout=14)
                elapsed = time.monotonic() - started
                fresh, _, pixel_bytes = viewer()
                with fresh:
                    pixels = 0
                    for _ in range(5):
                        fresh.sendall(struct.pack("!BBHHHH", 3, 0, 0, 0, 1, 1))
                        header = read(fresh, 4)
                        assert header[0] == 0
                        for _ in range(struct.unpack("!H", header[2:])[0]):
                            x, y, w, h, encoding = struct.unpack("!HHHHi", read(fresh, 12))
                            assert encoding == 0
                            read(fresh, w * h * pixel_bytes)
                            pixels += w * h
                        if pixels:
                            break
                        time.sleep(.1)
                    assert pixels, "Fresh viewer never received framebuffer pixels"
                    target = (101, 111) if mode == "manual" else (222, 233)
                    fresh.sendall(struct.pack("!BBHH", 5, 0, *target))
                    time.sleep(.2)
                    if mode == "manual":
                        expected = target
                    assert position() == expected, f"Incorrect input policy for {mode}"
                print(f"PASS {mode}: blocked viewer replaced in {elapsed:.2f}s; pixels and input policy verified", flush=True)
            finally:
                blocked.close()
    finally:
        manager.terminate()
        manager.wait(timeout=5)


if __name__ == "__main__":
    main()

