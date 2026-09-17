"""Explicit live acceptance checks, scoped to the named temporary QA bot.
Run inside the app container after deployment. Never prints session credentials.
"""
import base64
import asyncio
import websockets
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import httpx
from app.auth import AuthManager
from app.config import Settings
from app.db import Database
from app.store import Store

settings = Settings.from_env()
store = Store(Database(settings.database_path))
with store.db.read() as db:
    row = db.execute("SELECT id,user_id FROM agents WHERE name='QA Audit Bot 20260916' AND status='active'").fetchone()
if not row:
    raise SystemExit('Named QA bot not found; no live mutation performed')
agent, owner = row['id'], row['user_id']
auth = AuthManager(store.db, settings)
nonce = auth.create_nonce(owner)
base = settings.public_base_url.rstrip('/')
client = httpx.Client(base_url=base+'/bot/api/', headers={'Origin':base,'User-Agent':'BotMode-Acceptance-QA'}, timeout=110)
report = {'phase': sys.argv[1], 'checks': [], 'source': 'live-public-api'}

def api(method, path, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.is_error:
        raise RuntimeError(f'{method} {path} returned {response.status_code}: {response.text[:300]}')
    return response.json()

def check(name, value=True):
    if not value:
        raise AssertionError(name)
    report['checks'].append(name)
    print('PASS: '+name, flush=True)

def submit(prompt, title, file_ids=None):
    conversation = api('POST', 'conversations', json={'agent_id':agent,'title':title})['conversation']['id']
    sent = api('POST',f'conversations/{conversation}/messages',json={'content':prompt,'file_ids':file_ids or []})
    return conversation, sent['task']['id']

def wait_task(task, timeout=420):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=api('GET','tasks/'+task)['task']
        if result['status'] in ('completed','failed','cancelled'):
            report['task_id']=task
            report['task_status']=result['status']
            if result['status']!='completed':
                raise RuntimeError('QA task did not complete: '+str(result.get('error_message')))
            return result
        time.sleep(2)
    raise TimeoutError('QA task did not finish within acceptance timeout')

try:
    api('POST','auth/exchange',json={'nonce':nonce['nonce']})
    check('Authenticated separate QA session')
    phase=sys.argv[1]
    if phase=='basic':
        memory=api('POST','memory',json={'scope':'private','agent_id':agent,'content':'Temporary QA acceptance memory','memory_key':'qa-acceptance'})['memory']
        api('DELETE',f'memory/{memory["id"]}',params={'agent_id':agent})
        check('Private memory created and deleted through public API')
        text=b'Temporary QA upload, safe to delete.'
        file=api('POST','files',data={'agent_id':agent},files={'file':('qa-acceptance.txt',text,'text/plain')})['file']
        downloaded=client.get(f'files/{file["id"]}/download')
        check('Upload and authenticated download match',downloaded.content==text)
        api('DELETE',f'files/{file["id"]}')
        check('QA upload deleted')
        check('Live runtime connected',api('GET','runtime/account')['connected'])
    elif phase=='computer':
        result=api('POST',f'agents/{agent}/desktop')['desktop']
        check('Private computer started',result['running'])
        api('POST',f'agents/{agent}/desktop/action',json={'action':'navigate','text':'https://example.com'})
        time.sleep(3)
        shot=api('POST',f'agents/{agent}/desktop/action',json={'action':'screenshot'})['result']
        output=Path('/data/qa-evidence'); output.mkdir(exist_ok=True)
        (output/'live-private-computer.png').write_bytes(base64.b64decode(shot['image_url'].split(',',1)[1]))
        check('Real desktop screenshot captured',shot['width']==1366)
        view=client.get(base+result['view_url'])
        check('Authenticated noVNC page available',view.status_code==200 and b'noVNC' in view.content)
        async def rfb():
            cookie='; '.join(k+'='+v for k,v in client.cookies.items())
            async with websockets.connect(base.replace('https:', 'wss:')+f'/bot/api/agents/{agent}/desktop/view/websockify', origin=base, additional_headers={'Cookie':cookie}, subprotocols=['binary'], open_timeout=20) as socket:
                return (await asyncio.wait_for(socket.recv(),10)).startswith(b'RFB ')
        check('Public authenticated remote viewer socket connected',asyncio.run(rfb()))
        check('QA computer paused',not api('DELETE',f'agents/{agent}/desktop')['desktop']['running'])
        check('QA computer resumed',api('POST',f'agents/{agent}/desktop')['desktop']['running'])
        time.sleep(3)
        check('Remote viewer socket reconnected after resume',asyncio.run(rfb()))
        shot=api('POST',f'agents/{agent}/desktop/action',json={'action':'screenshot'})['result']
        (output/'live-private-computer-resumed.png').write_bytes(base64.b64decode(shot['image_url'].split(',',1)[1]))

    elif phase=='learning':
        document=io.BytesIO()
        with zipfile.ZipFile(document,'w') as archive:
            archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>QA document secret word is marigold.</w:t></w:r></w:p></w:document>')
        upload=api('POST','files',data={'agent_id':agent},files={'file':('qa-document.docx',document.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})['file']
        conversation,task=submit('This is an authorized QA test. Use files_read to read qa-document.docx. Verify its secret word. Then use skills_save to save a private procedure named QA document reading, with trigger DOCX document reading, steps listing files and reading the selected DOCX with files_read, and evidence quoting the observed word. Do not put the word itself in the procedure steps. Finally reply with the exact word from the document.','QA document and learning',[upload['id']])
        wait_task(task)
        messages=api('GET',f'conversations/{conversation}/messages')['messages']
        check('Bot read actual uploaded DOCX','marigold' in messages[-1]['content'].lower())
        skills=api('GET',f'agents/{agent}/skills')['skills']
        skill=next(s for s in skills if s['name']=='qa document reading')
        check('Procedure promoted after successful task',skill['enabled'])
        api('PATCH',f'agents/{agent}/skills/{skill["id"]}',json={'enabled':False})
        check('Learned procedure disabled',not next(s for s in api('GET',f'agents/{agent}/skills')['skills'] if s['id']==skill['id'])['enabled'])
        api('PATCH',f'agents/{agent}/skills/{skill["id"]}',json={'enabled':True})
        api('DELETE',f'files/{upload["id"]}')
    elif phase=='image':
        conversation,task=submit('Authorized image-generation QA test: use image_generate once to create a small square image of a single smooth blue ceramic sphere on an off-white background, soft studio light, no text. Include the resulting image in your response.','QA image generation')
        wait_task(task,600)
        messages=api('GET',f'conversations/{conversation}/messages')['messages']
        files=api('GET','files',params={'agent_id':agent})['files']
        images=[f for f in files if f['relative_path'].startswith('generated-images/')]
        check('Real KIE image persisted',bool(images))
        result=client.get(f'files/{images[0]["id"]}/download')
        check('Generated image downloads',result.status_code==200 and result.headers.get('content-type','').startswith('image/'))
        check('Image link persisted in chat','/bot/api/files/' in messages[-1]['content'])
        report['file_id']=images[0]['id']
        output=Path('/data/qa-evidence');output.mkdir(exist_ok=True)
        (output/'live-generated-image.png').write_bytes(result.content)
    elif phase=='cancel':
        conversation,task=submit('QA cancellation test. Write all integers from 1 to 3000, each on a separate line, without tools.','QA cancellation')
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            with store.db.read() as db:
                started=db.execute("SELECT 1 FROM task_events WHERE task_id=? AND event_type='turn.started'",(task,)).fetchone()
            if started:
                break
            time.sleep(.2)
        check('Task genuinely started before Stop',bool(started))
        result=api('POST',f'tasks/{task}/cancel')['task']
        check('Stop cancelled durable task',result['status']=='cancelled')
        time.sleep(2)
        check('Cancelled task stayed cancelled',api('GET',f'tasks/{task}')['task']['status']=='cancelled')
    else:
        raise ValueError('Unknown QA phase')
finally:
    try:
        api('POST','auth/logout')
    finally:
        client.close()
    output=Path('/data/qa-evidence');output.mkdir(exist_ok=True)
    (output/f'live-{sys.argv[1]}.json').write_text(json.dumps(report,indent=2))

