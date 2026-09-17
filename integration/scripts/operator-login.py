#!/usr/bin/env python3
"""Issue a short-lived, one-use login URL from a trusted server terminal."""
import argparse
from app.auth import AuthManager
from app.config import Settings
from app.db import Database

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--user-id', required=True, help='Stable owner ID; use the Telegram user ID when connecting Hermes')
args = parser.parse_args()
settings = Settings.from_env()
if not settings.public_base_url:
    parser.error('Configure BOT_PUBLIC_BASE_URL first')
result = AuthManager(Database(settings.database_path), settings).create_nonce(args.user_id)
print(result['url'])
print('Private one-use sign-in link. Open it yourself before it expires; do not share it.')

