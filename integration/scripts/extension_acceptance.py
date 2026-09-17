"""Harmless deployed extension checks. Run inside the service container."""
import json, os, time, uuid
from pathlib import Path
import httpx
from app.auth import AuthManager
from app.config import Settings
from app.db import Database
from app.store import Store

s=Settings.from_env();store=Store(Database(s.database_path));owner=os.environ['BOT_TELEGRAM_BRIDGE_OWNER_ID']
base=s.public_base_url.rstrip('/');c=httpx.Client(base_url=base+'/bot/api/',headers={'Origin':base},timeout=90)
def api(method,path,**kwargs):
 r=c.request(method,path,**kwargs)
 if r.is_error:raise RuntimeError(f'{path}: HTTP {r.status_code} '+str(r.json().get('error',{}).get('code','')))
 return r.json()
api('POST','auth/exchange',json={'nonce':AuthManager(store.db,s).create_nonce(owner)['nonce']})
chief=next(a for a in api('GET','agents')['agents'] if a['name']=='Chief')
agent=chief['id'];home=api('GET',f'agents/{agent}/home')['conversation']['id'];report={}
report['status']=api('GET','extensions/status')
connections=api('GET','connections',params={'q':'github'})
report['github_active']=any(a['toolkit']=='github' and a['status']=='ACTIVE' for a in connections['accounts'])
assert report['github_active']
secret='TEST-PRIVATE-'+uuid.uuid4().hex
field=api('POST',f'agents/{agent}/private-fields',json={'label':'Temporary verification','purpose':'Verify protected input','value':secret,'remember':False})['field']
assert secret not in json.dumps(field)
assert secret not in json.dumps(api('GET',f'agents/{agent}/private-fields'))
api('DELETE',f'agents/{agent}/private-fields/{field["id"]}')
report['private_roundtrip']=True
teaching=api('POST',f'agents/{agent}/teachings',json={'name':'Temporary verification procedure','trigger':'Only on explicit test','steps':['Return the word Verified.'],'notes':'Disposable acceptance test.'})['teaching']
assert teaching['status']=='unverified'
changed=api('PATCH',f'agents/{agent}/teachings/{teaching["id"]}',json={'enabled':False})['teaching'];assert not changed['enabled']
api('DELETE',f'agents/{agent}/teachings/{teaching["id"]}')
report['teaching_roundtrip']=True
with store.db.read() as db:
 report['telegram_history_messages']=db.execute('SELECT count(*) FROM telegram_history_sources WHERE owner_id=?',(owner,)).fetchone()[0]
 report['telegram_memory_sources']=db.execute('SELECT count(*) FROM telegram_memory_sources WHERE owner_id=?',(owner,)).fetchone()[0]
assert report['telegram_history_messages']>0 and report['telegram_memory_sources']==2
from app.writing_style import lint
assert lint('Hi Sam, the revised invoice is attached. Please confirm the total by Friday.')['clean']
report['deployed_writing_linter']=True
out=Path('/data/qa-evidence/expansion-20260917');out.mkdir(parents=True,exist_ok=True);(out/'live-extension-checks.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report))

