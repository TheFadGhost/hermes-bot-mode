#!/usr/bin/env python3
"""Run on the app host: hidden prompts; credentials never enter shell history.

sudo python3 /opt/hermes-bot-mode/integration/scripts/configure-providers.py
No service restart is needed. Keep the credential file out of source/backups.
"""
import argparse
import getpass
import json
import os
import re
from pathlib import Path
import tempfile


def main():
    parser = argparse.ArgumentParser(description="Configure Hermes connection and dictation providers")
    parser.add_argument("--path", default="/var/lib/hermes-bot-mode/provider-keys.json")
    parser.add_argument("--uid", type=int, default=10001)
    args = parser.parse_args()
    path = Path(args.path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    values = json.loads(path.read_text()) if path.exists() else {}
    for key, label in (("OPENROUTER_API_KEY", "OpenRouter"), ("COMPOSIO_API_KEY", "Composio")):
        value = getpass.getpass(f"{label} API key (hidden; Enter keeps existing): ").strip()
        if value:
            value = re.sub(r'^(?:export\s+)?' + re.escape(key) + r'\s*=\s*', '', value).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if not value or any(c.isspace() for c in value) or len(value) > 4096:
                raise SystemExit("Invalid key format; nothing saved")
            values[key] = value
    handle, temporary = tempfile.mkstemp(prefix=".providers-", dir=path.parent)
    try:
        with os.fdopen(handle, "w") as stream:
            json.dump(values, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        if hasattr(os, "chown"):
            os.chown(temporary, args.uid, args.uid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print("Saved securely. Refresh Connections or try the microphone in Hermes.")


if __name__ == "__main__":
    main()

