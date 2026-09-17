#!/usr/bin/env python3
"""Install reviewed bridge files without restarting Hermes or starting a poller."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def write_private(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(content)
    os.chmod(path, 0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home() / '.hermes')
    parser.add_argument('--owner-id', required=True, help='Authorized private Telegram user ID; never a model parameter')
    parser.add_argument('--url', default='http://127.0.0.1:9120/bot/api/internal/telegram')
    parser.add_argument('--write-timer', action='store_true', help='Write inactive user systemd units; does not start them')
    parser.add_argument('--reuse-config', action='store_true', help='Keep an existing private configuration with matching owner')
    args = parser.parse_args()
    root = args.home.expanduser().resolve()
    if any(char in str(root) + args.url + args.owner_id for char in '\r\n'):
        parser.error('Invalid configuration')
    source = Path(__file__).resolve().parents[1] / 'hermes_bridge'
    destination = root / 'plugins' / 'bot-mode-bridge'
    config_path = root / 'bot-mode-bridge.json'
    if destination.is_symlink() or config_path.is_symlink():
        parser.error('Bridge installation/configuration must not be symlinks')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup = root / 'bot-mode-bridge-install-backups' / stamp
    if destination.exists():
        shutil.copytree(destination, backup / 'plugin')
    if config_path.exists():
        backup.mkdir(parents=True, exist_ok=True)
        shutil.copy2(config_path, backup / 'config.json')
        os.chmod(backup / 'config.json', 0o600)
    if args.reuse_config:
        config = json.loads(config_path.read_text(encoding='utf-8'))
        if config.get('owner_id') != args.owner_id:
            parser.error('Existing configuration belongs to a different owner')
    else:
        secret = getpass.getpass('Existing Bot Mode bridge secret (hidden): ')
        if len(secret.strip()) < 32:
            parser.error('Bridge secret must contain at least 32 characters')
        config = {'owner_id': args.owner_id, 'url': args.url, 'secret': secret.strip()}
    os.environ['HERMES_HOME'] = str(root)
    # Validate before replacing the live configuration.
    sys.path.insert(0, str(source))
    from client import validate_configuration
    validate_configuration(config)
    write_private(config_path, json.dumps(config))
    destination.mkdir(parents=True, exist_ok=True)
    for filename in ('__init__.py', 'client.py', 'sync.py', 'plugin.yaml'):
        shutil.copy2(source / filename, destination / filename)
    if args.write_timer:
        units = Path.home() / '.config' / 'systemd' / 'user'
        quote = json.dumps
        service = ('[Unit]\nDescription=Bot Mode shared memory sync\nAfter=network-online.target\n\n'
                   '[Service]\nType=oneshot\nUMask=0077\n'
                   f'Environment={quote("HERMES_HOME=" + str(root))}\n'
                   f'ExecStart={quote(sys.executable)} {quote(str(destination / "sync.py"))}\n'
                   'NoNewPrivileges=true\nPrivateTmp=true\nTimeoutStartSec=60\n')
        write_private(units / 'hermes-bot-mode-sync.service', service)
        write_private(units / 'hermes-bot-mode-sync.timer', '[Unit]\nDescription=Refresh shared Bot Mode memory\n\n[Timer]\nOnBootSec=2min\nOnUnitActiveSec=5min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n')
    print('Bridge files installed. No gateway restart, provider call, plugin enable, or timer start was performed.')
    print('Enable bot-mode-bridge using the existing Hermes CLI in its running environment, then review/restart that gateway during a safe window.')
    if args.write_timer:
        print('After review: systemctl --user daemon-reload && systemctl --user enable --now hermes-bot-mode-sync.timer')


if __name__ == '__main__':
    main()

