"""Local-only bridge client; no provider credentials or arbitrary proxy path."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


def home() -> Path:
    return Path(os.environ.get('HERMES_HOME', str(Path.home() / '.hermes'))).resolve()


def configuration() -> dict:
    path = home() / 'bot-mode-bridge.json'
    if path.is_symlink() or (os.name == 'posix' and stat.S_IMODE(path.stat().st_mode) & 0o077):
        raise ValueError('Bridge configuration must be a private regular file')
    config = json.loads(path.read_text(encoding='utf-8'))
    validate_configuration(config)
    return config


def validate_configuration(config: dict) -> None:
    parsed = urlsplit(config.get('url', ''))
    if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', '::1'}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path.rstrip('/') != '/bot/api/internal/telegram'):
        raise ValueError('Bridge requires its fixed loopback URL')
    if not str(config.get('owner_id', '')).strip() or len(str(config.get('secret', ''))) < 32:
        raise ValueError('Bridge is not configured')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Bridge redirects are forbidden')


def call(endpoint: str, payload: dict, config: dict | None = None) -> dict:
    if endpoint not in {'action', 'memory/sync', 'history/import', 'history/search'}:
        raise ValueError('Unsupported bridge operation')
    config = config or configuration()
    request = Request(config['url'].rstrip('/') + '/' + endpoint,
                      data=json.dumps(payload).encode(), method='POST',
                      headers={'Authorization': 'Bearer ' + config['secret'], 'Content-Type': 'application/json'})
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=30) as response:
        raw = response.read(1000001)
        if len(raw) > 1000000:
            raise ValueError('Bridge response is too large')
        result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('Invalid bridge response')
    return result

