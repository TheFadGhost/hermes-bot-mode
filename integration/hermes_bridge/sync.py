"""One-shot shared-memory synchronization; scheduled without a Telegram poller."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import math
import tempfile
from pathlib import Path

try:
    from .client import call, configuration, home
except ImportError:
    from client import call, configuration, home


@contextlib.contextmanager
def locked(path: Path):
    import fcntl  # Installation and scheduled sync run on the Linux gateway host.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+', encoding='utf-8') as handle:
        os.chmod(path, 0o600)
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.bridge-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def visible_content(value) -> str:
    """Decode Hermes' explicit multimodal sentinel, selecting text only."""
    if not isinstance(value,str): return ''
    if not value.startswith('\x00json:'): return value
    data=json.loads(value[len('\x00json:'):])
    parts=data if isinstance(data,list) else [data]
    return '\n'.join(part['text'] for part in parts if isinstance(part,dict)
                     and part.get('type') in ('text','input_text','output_text') and isinstance(part.get('text'),str))


SYNTHETIC_PREFIXES = (
    '[CONTEXT COMPACTION — REFERENCE ONLY]',
    '[PRIOR CONTEXT — for reference only; not a new message]',
    '[Your active task list was preserved across context compression]',
)


def history_exclusion(db, row, columns) -> str | None:
    """Reject internal context and proven compaction copies, never text alone."""
    content = visible_content(row['content'])
    if content.lstrip().startswith(SYNTHETIC_PREFIXES):
        return 'synthetic_context'
    if 'compacted' not in columns:
        return None
    previous = db.execute('SELECT timestamp FROM messages WHERE session_id=? AND role=? AND content=? AND id<? AND compacted=1 ORDER BY id LIMIT 1',
                          (row['session_id'],row['role'],row['content'],row['id'])).fetchone()
    if previous is None:
        return None
    if float(previous['timestamp']) == float(row['timestamp']):
        return 'compaction_replay'
    # Hermes inserts retained transcript rows in the same transaction as its
    # synthetic marker, assigning microsecond-spaced fresh timestamps. Require
    # this positive evidence; a later real repetition must remain a new turn.
    markers = db.execute('SELECT content FROM messages WHERE session_id=? AND id<? AND timestamp<=? AND timestamp>=? ORDER BY id DESC LIMIT 100',
                         (row['session_id'],row['id'],row['timestamp'],float(row['timestamp'])-0.05)).fetchall()
    if any(visible_content(marker['content']).lstrip().startswith(SYNTHETIC_PREFIXES[:2]) for marker in markers):
        return 'compaction_replay'
    return None


def read_history_batch(root: Path, owner_id: str, cursor: int, *, limit: int = 50) -> dict:
    """Read only owner Telegram DMs from the original database, never mutate it."""
    path=root/'state.db'
    if not path.exists(): return {'available':False,'reason':'history_database_missing','messages':[],'cursor':cursor}
    if path.is_symlink() or not path.is_file(): raise ValueError('Unsafe history database')
    with contextlib.closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=5)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        sessions={row['name'] for row in db.execute('PRAGMA table_info(sessions)')}
        columns={row['name'] for row in db.execute('PRAGMA table_info(messages)')}
        if not {'id','source','user_id','chat_id','chat_type'}<=sessions or not {'id','session_id','role','content','timestamp'}<=columns:
            return {'available':False,'reason':'history_schema_unavailable','messages':[],'cursor':cursor}
        # Compacted rows retain visible history. Inactive non-compacted rows
        # were rewound/deleted and must not silently reappear in the other app.
        visibility=" AND (m.active=1 OR m.compacted=1)" if {'active','compacted'}<=columns else (' AND m.active=1' if 'active' in columns else '')
        if 'tool_calls' in columns:
            visibility+=" AND (m.role='user' OR m.tool_calls IS NULL OR m.tool_calls='' OR m.tool_calls='[]')"
        rows=db.execute("SELECT m.id,m.session_id,m.role,m.content,m.timestamp FROM messages m JOIN sessions s ON s.id=m.session_id WHERE s.source='telegram' AND s.user_id=? AND s.chat_id=? AND s.chat_type='dm' AND m.role IN ('user','assistant') AND m.id>?"+visibility+' ORDER BY m.id LIMIT ?',
                        (owner_id,owner_id,cursor,min(50,max(1,limit)))).fetchall()
        messages=[]
        used=0
        next_cursor=cursor
        for row in rows:
            if history_exclusion(db,row,columns):
                next_cursor=int(row['id'])
                continue
            content=visible_content(row['content'])
            timestamp=float(row['timestamp'])
            if not math.isfinite(timestamp) or timestamp<0 or timestamp>253402300799:
                raise ValueError('Invalid source message timestamp')
            item={'source_id':int(row['id']),'session_id':row['session_id'],'role':row['role'],'content':content,'timestamp':timestamp}
            size=len(json.dumps(item,ensure_ascii=False).encode())
            if size>1100000: raise ValueError('A source message exceeds the exact archive batch limit')
            if used+size>1100000: break
            if content.strip():
                messages.append(item)
                used+=size
            next_cursor=int(row['id'])
        return {'available':True,'messages':messages,'cursor':next_cursor,'more':bool(rows) and (len(rows)==min(50,max(1,limit)) or next_cursor<int(rows[-1]['id']))}


def sync_history(config: dict, root: Path, request=call) -> dict:
    path=root/'state.db'
    if not path.exists(): return {'available':False,'reason':'history_database_missing','imported':0}
    checkpoint=root/'bot-mode-history-cursor.json'
    identity=[path.stat().st_dev,path.stat().st_ino]
    saved={}
    if checkpoint.exists():
        if checkpoint.is_symlink(): raise ValueError('Unsafe history cursor')
        saved=json.loads(checkpoint.read_text(encoding='utf-8'))
    cursor=int(saved.get('cursor',0)) if saved.get('owner_id')==config['owner_id'] and saved.get('database_identity')==identity else 0
    imported=updated=0
    for _ in range(10):
        batch=read_history_batch(root,str(config['owner_id']),cursor)
        if not batch['available']: return {**batch,'imported':imported}
        if batch['messages']:
            result=request('history/import',{'source_owner':str(config['owner_id']),'messages':batch['messages']},config)
            if not isinstance(result.get('imported'),int) or not isinstance(result.get('updated'),int):
                raise ValueError('Invalid history acknowledgement')
            imported+=result['imported']
            updated+=result['updated']
        # Commit the cursor only after the backend commits this batch. If the
        # response is lost, replay safely uses the backend provenance key.
        cursor=batch['cursor']
        atomic_write(checkpoint,json.dumps({'owner_id':config['owner_id'],'database_identity':identity,'cursor':cursor}))
        if not batch['more']: break
    return {'available':True,'imported':imported,'updated':updated,'more':batch['more']}


def sync(*, config: dict | None = None, root: Path | None = None, request=call) -> dict:
    config = config or configuration()
    root = root or home()
    memories = root / 'memories'
    with locked(root / 'bot-mode-bridge.sync.lock'):
        documents = {}
        for name in ('USER.md', 'MEMORY.md'):
            path = memories / name
            # Match original Hermes memory_tool.py's .md.lock convention.
            with locked(path.with_suffix('.md.lock')):
                if not path.exists():
                    continue  # Missing file is not consent to delete memory.
                if path.is_symlink() or path.stat().st_size > 200000:
                    raise ValueError('Unsafe or oversized memory source')
                value = path.read_text(encoding='utf-8')
                if len(value) > 50000:
                    raise ValueError('Memory source exceeds bridge limit')
                documents[name] = value
                digest = hashlib.sha256(value.encode()).hexdigest()
                backup = root / 'bot-mode-bridge-backups' / f'{name}.{digest}.bak'
                if not backup.exists():
                    atomic_write(backup, value)
        result = request('memory/sync', {'source_owner':str(config['owner_id']),'documents': documents}, config)
        expected=hashlib.sha256(str(config['owner_id']).encode()).hexdigest()
        if result.get('owner_fingerprint')!=expected:
            raise PermissionError('Bridge owner could not be verified')
        rows = result.get('shared_memory')
        if not isinstance(rows, list) or len(rows) > 500:
            raise ValueError('Invalid shared memory response')
        target = memories / 'BOT_MODE_SHARED.json'
        # An owner label prevents a stale mirror surviving account reconfiguration.
        atomic_write(target, json.dumps({'owner_id': config['owner_id'], 'shared_memory': rows}, ensure_ascii=False))
        history=sync_history(config,root,request=request)
        return {'imported_documents': result.get('imported_documents', 0), 'exported_facts': len(rows),'history':history}


def search_shared(query: str, *, root: Path | None = None, owner_id: str | None = None) -> dict:
    config = configuration() if owner_id is None else {'owner_id': owner_id}
    path = (root or home()) / 'memories' / 'BOT_MODE_SHARED.json'
    if not path.exists():
        return {'memory': [], 'hint': 'Set sync=true to refresh shared memory.'}
    if path.is_symlink() or path.stat().st_size > 1000000:
        raise ValueError('Unsafe memory mirror')
    payload = json.loads(path.read_text(encoding='utf-8'))
    if payload.get('owner_id') != config['owner_id']:
        raise PermissionError('Memory mirror belongs to another owner')
    terms = set(re.findall(r'\w{2,}', query.casefold()[:500]))
    rows = payload['shared_memory']
    if terms:
        rows = [row for row in rows if terms.intersection(re.findall(r'\w{2,}', (str(row.get('memory_key', '')) + ' ' + str(row.get('content', ''))).casefold()))]
    return {'memory': [{**row, 'content': str(row.get('content', ''))[:4000]} for row in rows[:10]]}


if __name__ == '__main__':
    try:
        print(json.dumps(sync()))
    except Exception:
        print('Shared memory sync failed; original files preserved.')
        raise SystemExit(1)

