"""Owner/bot scoped private values. Plaintext has no public read interface."""
from __future__ import annotations

import base64
import json
import os
import stat
import time
import uuid
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .errors import APIError


class PrivateFields:
    def __init__(self, store, key_path: Path):
        self.store = store
        self.key_path = key_path
        self._cipher = None
        try:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            # The key is outside agent workspaces. Never regenerate a lost key
            # when encrypted records exist; that would silently destroy access.
            with store.db.transaction() as db:
                db.execute("""CREATE TABLE IF NOT EXISTS private_fields (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                    label TEXT NOT NULL, purpose TEXT NOT NULL, ciphertext BLOB NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, one_time INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'ready',
                    claimed_by TEXT, created_at INTEGER NOT NULL,
                    FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE)""")
                count = db.execute("SELECT COUNT(*) FROM private_fields").fetchone()[0]
            if not key_path.exists() and not count:
                try:
                    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    pass
                else:
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(AESGCM.generate_key(bit_length=256))
                        stream.flush()
                        os.fsync(stream.fileno())
            if key_path.is_symlink():
                raise ValueError('Invalid key path')
            if os.name == 'posix' and stat.S_IMODE(key_path.stat().st_mode) & 0o077:
                raise ValueError('Vault key must be private')
            key = key_path.read_bytes()
            if len(key) != 32:
                raise ValueError('Invalid key')
            self._cipher = AESGCM(key)
        except (OSError, ValueError):
            # Core messaging must still start if the vault needs recovery.
            self._cipher = None

    @property
    def available(self):
        return self._cipher is not None

    @staticmethod
    def _aad(user_id, agent_id, field_id, revision):
        return json.dumps([user_id, agent_id, field_id, revision], separators=(',', ':')).encode()

    @staticmethod
    def public(row):
        return {key: bool(row[key]) if key == 'one_time' else row[key]
                for key in ('id', 'label', 'purpose', 'expires_at', 'one_time', 'revision')}

    def save(self, user_id, agent_id, *, label, purpose, value, remember=False):
        self.store.get_agent(user_id, agent_id)
        if not self.available:
            raise APIError(503, 'private_unavailable', 'Private input needs administrator recovery.')
        if not isinstance(value, str) or not 1 <= len(value) <= 8192:
            raise APIError(422, 'private_invalid', 'Enter a private value of up to 8,192 characters.')
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 100:
            raise APIError(422, 'private_label', 'Give this private field a short name.')
        if not isinstance(purpose, str) or len(purpose) > 500:
            raise APIError(422, 'private_purpose', 'Use a purpose of up to 500 characters.')
        field_id, stamp = uuid.uuid4().hex, int(time.time())
        nonce = os.urandom(12)
        ciphertext = nonce + self._cipher.encrypt(nonce, value.encode(), self._aad(user_id, agent_id, field_id, 1))
        with self.store.db.transaction() as db:
            db.execute("DELETE FROM private_fields WHERE expires_at < ? AND state != 'reserved'", (stamp,))
            db.execute("INSERT INTO private_fields(id,user_id,agent_id,label,purpose,ciphertext,one_time,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (field_id,user_id,agent_id,label.strip(),purpose.strip(),ciphertext,not remember,stamp+(2592000 if remember else 3600),stamp))
        return self.metadata(user_id, agent_id, field_id)

    def metadata(self, user_id, agent_id, field_id):
        with self.store.db.read() as db:
            row = db.execute("SELECT * FROM private_fields WHERE id=? AND user_id=? AND agent_id=? AND state='ready' AND expires_at>?",
                             (field_id,user_id,agent_id,int(time.time()))).fetchone()
        if not row:
            raise APIError(404, 'private_missing', 'Private field is unavailable or expired. Enter it again.')
        return self.public(row)

    def list(self, user_id, agent_id):
        self.store.get_agent(user_id, agent_id)
        with self.store.db.read() as db:
            rows = db.execute("SELECT * FROM private_fields WHERE user_id=? AND agent_id=? AND state='ready' AND expires_at>? ORDER BY created_at DESC LIMIT 100",
                              (user_id,agent_id,int(time.time()))).fetchall()
        return [self.public(row) for row in rows]

    def delete(self, user_id, agent_id, field_id):
        self.store.get_agent(user_id, agent_id)
        with self.store.db.transaction() as db:
            row = db.execute("SELECT state FROM private_fields WHERE id=? AND user_id=? AND agent_id=?", (field_id,user_id,agent_id)).fetchone()
            if row and row['state'] == 'reserved':
                raise APIError(409, 'private_in_use', 'An approved action is using this field. Wait for its result.')
            db.execute("DELETE FROM private_fields WHERE id=? AND user_id=? AND agent_id=?", (field_id,user_id,agent_id))

    def claim(self, user_id, agent_id, references, action_id):
        """Reserve immutable IDs atomically before exposing plaintext to broker.

        The caller never returns these values to the model or HTTP response.
        """
        if not self.available:
            raise APIError(503, 'private_unavailable', 'Private input is unavailable.')
        values = {}
        with self.store.db.transaction(immediate=True) as db:
            for field_id, revision in references.items():
                row = db.execute("SELECT * FROM private_fields WHERE id=? AND user_id=? AND agent_id=? AND revision=? AND state='ready' AND expires_at>?",
                                 (field_id,user_id,agent_id,revision,int(time.time()))).fetchone()
                if not row:
                    raise APIError(409,'private_changed','A private field expired or changed. Review a new action.')
                raw = bytes(row['ciphertext'])
                try:
                    values[field_id] = self._cipher.decrypt(raw[:12],raw[12:],self._aad(user_id,agent_id,field_id,revision)).decode()
                except Exception:
                    raise APIError(503,'private_unavailable','Private input could not be opened. Administrator recovery is needed.') from None
                db.execute("UPDATE private_fields SET state='reserved',claimed_by=? WHERE id=?", (action_id,field_id))
        return values

    def finish(self, action_id, *, uncertain=False, consumed=True):
        with self.store.db.transaction() as db:
            if uncertain:
                db.execute("UPDATE private_fields SET state='quarantined' WHERE claimed_by=?", (action_id,))
            else:
                if consumed:
                    db.execute("DELETE FROM private_fields WHERE claimed_by=? AND one_time=1", (action_id,))
                db.execute("UPDATE private_fields SET state='ready',claimed_by=NULL WHERE claimed_by=?", (action_id,))


def provider_key(settings, name):
    """Reload credentials without restarting or passing them to Codex's env."""
    value = os.getenv(name, '')
    if value:
        return value
    path = Path(os.getenv('BOT_PROVIDER_KEYS_FILE', str(settings.database_path.parent / 'provider-keys.json')))
    try:
        values = json.loads(path.read_text())
        value = values.get(name, '')
        return value if isinstance(value, str) else ''
    except (OSError, ValueError, AttributeError):
        return ''

