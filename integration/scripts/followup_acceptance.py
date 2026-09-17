"""Harmless authenticated follow-up checks against the deployed app."""
import json
import time
import uuid
from pathlib import Path

import httpx
from app.auth import AuthManager
from app.config import Settings
from app.db import Database
from app.store import Store

s = Settings.from_env()
store = Store(Database(s.database_path))
with store.db.read() as db:
    row = db.execute("SELECT id,user_id FROM agents WHERE name='QA Grok Chief 20260917'").fetchone()
assert row, 'Named QA bot required'
agent_id, owner = row
base = s.public_base_url.rstrip('/')
client = httpx.Client(base_url=base+'/bot/api/', headers={'Origin': base}, timeout=60)
out = Path('/data/qa-evidence/followup-20260917')
out.mkdir(parents=True, exist_ok=True)
report = {'checks': [], 'passed': False}
memory_ids = []
conversation_id = None

def api(method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.is_error:
        raise RuntimeError(str(response.status_code)+' '+response.text[:300])
    return response.json()

def check(label, condition=True):
    assert condition, label
    report['checks'].append(label)
    print('PASS: '+label, flush=True)

try:
    nonce = AuthManager(store.db,s).create_nonce(owner)
    api('POST','auth/exchange',json={'nonce':nonce['nonce']})
    bots = api('GET','agents')['agents']
    check('Requested QA audit bot is deleted', not any(b['name']=='QA Audit Bot 20260916' for b in bots))
    usage = api('GET','runtime/usage')
    bucket = (usage.get('rateLimitsByLimitId') or {}).get('codex') or usage.get('rateLimits') or {}
    check('Live subscription usage exposes both windows', isinstance(bucket.get('primary',{}).get('usedPercent'),(int,float)) and isinstance(bucket.get('secondary',{}).get('usedPercent'),(int,float)))
    report['usage'] = {key:bucket.get(key) for key in ('primary','secondary','planType')}
    home = api('GET',f'agents/{agent_id}/home')['conversation']
    conversation_id = home['id']
    api('POST',f'conversations/{conversation_id}/restore')
    old = api('POST','memory',json={'scope':'private','agent_id':agent_id,'memory_key':'QA workshop booking','content':'The workshop booking is LARK-4100.','source':'followup QA','confidence':1})['memory']
    memory_ids.append(old['id'])
    corrected = api('POST','memory',json={'scope':'private','agent_id':agent_id,'memory_key':'QA workshop booking','content':'The corrected workshop booking is LARK-9820.','source':'followup QA correction','confidence':1,'supersedes_id':old['id']})['memory']
    memory_ids.append(corrected['id'])
    recall = api('GET','memory/search',params={'q':'Could you remind me what my workshop booking is please?','agent_id':agent_id})['memory']
    check('Natural question recalls correction and excludes old fact', any(m['id']==corrected['id'] for m in recall) and not any(m['id']==old['id'] for m in recall))
    check('Original memory remains readable',api('GET',f"memory/{old['id']}",params={'agent_id':agent_id})['memory']['content']==old['content'])
    result = api('POST',f'conversations/{conversation_id}/messages',json={'content':'Authorized image verification: use your native image generation tool to create one simple blue paper boat on a pale background. Generate the actual image, not code or instructions. Do not use KIE or any external paid API. Reply briefly.','client_request_id':str(uuid.uuid4())})
    task_id = result['task']['id']
    report['task_id'] = task_id
    deadline = time.monotonic()+360
    while time.monotonic()<deadline:
        task = api('GET',f'tasks/{task_id}')['task']
        if task['status'] in ('completed','failed','cancelled'):
            break
        time.sleep(2)
    report['task_status'] = task['status']
    check('Native Codex image turn completes',task['status']=='completed')
    with store.db.read() as db:
        events = db.execute('SELECT event_type,data_json FROM task_events WHERE task_id=? ORDER BY id',(task_id,)).fetchall()
    successes = [json.loads(e[1]) for e in events if e[0]=='tool.completed' and json.loads(e[1]).get('tool')=='image_generate' and json.loads(e[1]).get('success')]
    check('Native image saved with Codex provenance',bool(successes) and successes[-1]['result']['provider']=='codex')
    asset = successes[-1]['result']
    report['image'] = asset
    response = client.get(f"files/{asset['file_id']}/download")
    check('Actual image downloads',response.status_code==200 and response.headers.get('content-type','').startswith('image/'))
    (out/'native-image.png').write_bytes(response.content)
    messages = api('GET',f'conversations/{conversation_id}/messages')['messages']
    check('Image survives saved transcript',any(asset['file_id'] in m['content'] for m in messages))
    report['passed'] = True
finally:
    for memory_id in reversed(memory_ids):
        api('DELETE',f'memory/{memory_id}',params={'agent_id':agent_id})
    if conversation_id:
        api('POST',f'conversations/{conversation_id}/archive')
    (out/'acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    try:
        api('POST','auth/logout')
    finally:
        client.close()

