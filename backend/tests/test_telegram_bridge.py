from __future__ import annotations

import asyncio
import importlib.util
import json
import hashlib
import sqlite3
import sys
from pathlib import Path
from types import ModuleType

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.db import Database
from app.errors import APIError
from app.messenger import Messenger
from app.store import Store
from app.telegram_bridge import BridgeAction, TelegramBridge, HistoryBatch, HistoryQuery


@pytest.fixture
def bridge(tmp_path):
    store = Store(Database(tmp_path / 'bridge.sqlite'))
    class Tasks:
        def __init__(self): self.submitted = set()
        def submit(self, owner, task): self.submitted.add((owner, task))
        async def cancel(self, owner, task):
            store.get_task(owner, task)
            store.cancel_task(task)
            return store.get_task(owner, task)
    return TelegramBridge(store, Messenger(store), Tasks(), owner_id='1234', secret='s' * 40)


def run(bridge, operation, **kwargs):
    return asyncio.run(bridge.action(BridgeAction(operation=operation, **kwargs)))


def test_fixed_auth_and_no_owner_or_proxy_arguments(bridge):
    bridge.authenticate('Bearer ' + 's' * 40)
    for value in [None, '', 'Bearer wrong', 'Bearer ' + 's' * 39]:
        with pytest.raises(APIError): bridge.authenticate(value)
    with pytest.raises(ValidationError): BridgeAction(operation='bots', user_id='other')
    with pytest.raises(ValidationError): BridgeAction(operation='proxy', url='https://example.com')
    app, router = FastAPI(), APIRouter()
    @app.exception_handler(APIError)
    async def handle(request, error):
        return JSONResponse(status_code=error.status_code, content=error.as_dict())
    bridge.install_routes(router)
    app.include_router(router, prefix='/bot/api')
    with TestClient(app) as client:
        assert client.post('/bot/api/internal/telegram/action', json={'operation': 'bots'}).status_code == 401
        response = client.post('/bot/api/internal/telegram/action', headers={'Authorization': 'Bearer ' + 's' * 40}, json={'operation': 'bots'})
        assert response.json() == {'bots': []}
        assert client.post('/bot/api/internal/telegram/history/import',json={'source_owner':'1234','messages':[]}).status_code==401
        assert client.post('/bot/api/internal/telegram/history/import',headers={'Authorization':'Bearer '+'s'*40},json={'source_owner':'other','messages':[]}).status_code==403
        assert client.post('/bot/api/internal/telegram/memory/sync',headers={'Authorization':'Bearer '+'s'*40},json={'source_owner':'other','documents':{}}).status_code==403


def test_create_start_results_cancel_are_owner_bound_and_idempotent(bridge):
    first = run(bridge, 'create', request_id='create-1', name='Helper', instructions='Help')
    assert first == run(bridge, 'create', request_id='create-1', name='Helper', instructions='Help')
    with pytest.raises(APIError): run(bridge, 'create', request_id='create-1', name='Different')
    agent_id = first['bot']['id']
    started = run(bridge, 'start', agent_id=agent_id, request_id='start-1', content='Summarize these notes')
    repeated = run(bridge, 'start', agent_id=agent_id, request_id='start-1', content='Summarize these notes')
    assert repeated['task']['id'] == started['task']['id']
    assert repeated['duplicate'] is True
    assert len(bridge.tasks.submitted) == 1
    with pytest.raises(APIError): run(bridge, 'start', agent_id=agent_id, request_id='start-1', content='Different')
    task_id = started['task']['id']
    bridge.store.append_assistant_message('1234', task_id, 'Confirmed output')
    assert run(bridge, 'results', task_id=task_id)['messages'][0]['content'] == 'Confirmed output'
    assert run(bridge, 'cancel', task_id=task_id)['task']['status'] == 'cancelled'
    foreign = bridge.store.create_agent('someone-else', name='Foreign', model='test', instructions='')
    with pytest.raises(APIError): run(bridge, 'start', agent_id=foreign['id'], request_id='x', content='No')
    conversation = bridge.store.create_conversation('someone-else', foreign['id'], 'Private')
    _, foreign_task, _ = bridge.store.create_message_and_task('someone-else', conversation['id'], 'Private')
    with pytest.raises(APIError): run(bridge, 'results', task_id=foreign_task['id'])


def test_memory_import_dedup_replacement_empty_and_missing(bridge):
    assert bridge.sync_memory({'USER.md': 'Prefers concise answers'})['imported_documents'] == 1
    assert bridge.sync_memory({'USER.md': 'Prefers concise answers'})['imported_documents'] == 0
    old = bridge.store.list_memory('1234')[0]
    bridge.sync_memory({'USER.md': 'Prefers detailed answers'})
    current = bridge.store.list_memory('1234')
    assert len(current) == 1 and current[0]['supersedes_id'] == old['id']
    assert current[0]['source'] == 'telegram-file:USER.md'
    bridge.sync_memory({})
    assert bridge.store.list_memory('1234')
    bridge.sync_memory({'USER.md': ''})
    assert bridge.store.list_memory('1234') == []
    assert bridge.sync_memory({'USER.md': ''})['imported_documents'] == 0


def test_deleted_import_does_not_reappear_unchanged(bridge):
    bridge.sync_memory({'MEMORY.md': 'A shared fact'})
    bridge.store.delete_memory('1234', bridge.store.list_memory('1234')[0]['id'])
    bridge.sync_memory({'MEMORY.md': 'A shared fact'})
    assert bridge.store.list_memory('1234') == []
    bridge.sync_memory({'MEMORY.md': 'Second version'})
    bridge.sync_memory({'MEMORY.md': 'Third version'})
    bridge.store.delete_memory('1234', bridge.store.list_memory('1234')[0]['id'])
    bridge.sync_memory({'MEMORY.md': ''})
    assert bridge.store.list_memory('1234') == []


def test_export_only_active_shared_owner_facts_and_tracks_deletion(bridge):
    bot = run(bridge, 'create', request_id='bot', name='Bot')['bot']
    def save(owner, scope, content, agent=None, supersedes=None):
        return bridge.store.create_memory(owner, scope=scope, content=content, agent_id=agent,
            memory_key='fact', source='user', confidence=1, supersedes_id=supersedes)
    first = save('1234', 'shared', 'old')
    newest = save('1234', 'shared', 'new', supersedes=first['id'])
    save('1234', 'private', 'secret private', bot['id'])
    save('other', 'shared', 'foreign shared')
    bridge.sync_memory({'MEMORY.md': 'original Telegram source'})
    assert [row['content'] for row in bridge.sync_memory({})['shared_memory']] == ['new']
    bridge.store.delete_memory('1234', newest['id'])
    # Store semantics intentionally restore the previous version when its
    # replacement is deleted; bridge exports exactly the active shared set.
    assert [row['content'] for row in bridge.sync_memory({})['shared_memory']] == ['old']
    bridge.store.delete_memory('1234', first['id'])
    assert bridge.sync_memory({})['shared_memory'] == []


def plugin_module():
    path = Path(__file__).resolve().parents[2] / 'integration' / 'hermes_bridge' / '__init__.py'
    spec = importlib.util.spec_from_file_location('tested_hermes_bridge', path, submodule_search_locations=[str(path.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_plugin_uses_gateway_context_and_stable_request_id(monkeypatch):
    plugin = plugin_module()
    context = {'HERMES_SESSION_PLATFORM': 'telegram', 'HERMES_SESSION_USER_ID': '1234', 'HERMES_SESSION_CHAT_ID': '1234', 'HERMES_SESSION_MESSAGE_ID': '99'}
    session = ModuleType('gateway.session_context')
    session.get_session_env = lambda key: context.get(key, '')
    monkeypatch.setitem(sys.modules, 'gateway', ModuleType('gateway'))
    monkeypatch.setitem(sys.modules, 'gateway.session_context', session)
    monkeypatch.setattr(plugin, 'configuration', lambda: {'owner_id': '1234'})
    seen = []
    monkeypatch.setattr(plugin, 'call', lambda endpoint, payload, config: seen.append(payload) or {'ok': True})
    args = {'operation': 'start', 'agent_id': 'a', 'content': 'Work'}
    assert json.loads(plugin._handle(args)) == {'ok': True}
    plugin._handle(args)
    assert seen[0]['request_id'] == seen[1]['request_id']
    context['HERMES_SESSION_CHAT_ID'] = '-100group'
    assert 'error' in json.loads(plugin._handle(args))
    assert len(seen) == 2
    context['HERMES_SESSION_CHAT_ID'] = '1234'
    assert 'error' in json.loads(plugin._handle({**args, 'owner_id': 'other'}))


@pytest.mark.parametrize('url', ['https://example.com/bot/api/internal/telegram',
    'http://127.0.0.1:9120/arbitrary', 'http://user:pass@127.0.0.1:9120/bot/api/internal/telegram',
    'http://127.0.0.1:9120/bot/api/internal/telegram?redirect=elsewhere'])
def test_client_refuses_external_or_arbitrary_endpoints(url):
    plugin_module()
    from tested_hermes_bridge.client import validate_configuration
    with pytest.raises(ValueError):
        validate_configuration({'url': url, 'owner_id': '1234', 'secret': 's' * 40})


@pytest.mark.skipif(sys.platform == 'win32', reason='Original gateway uses Linux flock')
def test_sync_preserves_originals_and_last_good_mirror(tmp_path):
    plugin_module()
    from tested_hermes_bridge.sync import sync, search_shared
    memories = tmp_path / 'memories'
    memories.mkdir()
    user = memories / 'USER.md'
    user.write_text('Original profile', encoding='utf-8')
    config = {'owner_id': '1234'}
    def request(endpoint, payload, supplied):
        assert payload == {'source_owner':'1234','documents': {'USER.md': 'Original profile'}}
        return {'shared_memory': [{'id': 1, 'content': 'Shared fact'}], 'imported_documents': 1,
                'owner_fingerprint':hashlib.sha256(b'1234').hexdigest()}
    sync(config=config, root=tmp_path, request=request)
    assert user.read_text() == 'Original profile'
    assert list((tmp_path / 'bot-mode-bridge-backups').glob('USER.md.*.bak'))
    assert search_shared('Shared', root=tmp_path, owner_id='1234')['memory'][0]['id'] == 1
    mirror = (memories / 'BOT_MODE_SHARED.json').read_bytes()
    def broken(*args): raise RuntimeError('Network down')
    with pytest.raises(RuntimeError): sync(config=config, root=tmp_path, request=broken)
    assert (memories / 'BOT_MODE_SHARED.json').read_bytes() == mirror
    with pytest.raises(PermissionError): search_shared('', root=tmp_path, owner_id='other')


def original_history(root):
    with sqlite3.connect(root/'state.db') as db:
        db.executescript('''CREATE TABLE sessions(id TEXT PRIMARY KEY,source TEXT,user_id TEXT,chat_id TEXT,chat_type TEXT);
        CREATE TABLE messages(id INTEGER PRIMARY KEY,session_id TEXT,role TEXT,content TEXT,timestamp REAL,tool_calls TEXT,reasoning TEXT,active INTEGER DEFAULT 1,compacted INTEGER DEFAULT 0);''')
        db.executemany('INSERT INTO sessions VALUES(?,?,?,?,?)',[
            ('owner-dm','telegram','1234','1234','dm'),('foreign-dm','telegram','other','other','dm'),
            ('owner-group','telegram','1234','1234','group'),('wrong-chat','telegram','1234','other','dm'),
            ('cli','cli','1234','1234','dm'),('unknown','telegram',None,'1234','dm')])
        db.executemany('INSERT INTO messages(id,session_id,role,content,timestamp,tool_calls,reasoning,active,compacted) VALUES(?,?,?,?,?,?,?,?,?)',[
            (1,'owner-dm','user','Visible appointment reference',1000.25,None,None,1,0),
            (2,'owner-dm','assistant','Visible answer',1001.75,None,'Hidden chain of thought',1,0),
            (3,'foreign-dm','user','FOREIGN OWNER SECRET',1002,None,None,1,0),
            (4,'owner-group','user','GROUP SECRET',1003,None,None,1,0),
            (5,'wrong-chat','user','WRONG CHAT SECRET',1004,None,None,1,0),
            (6,'owner-dm','tool','TOOL SECRET',1005,None,None,1,0),
            (7,'owner-dm','system','SYSTEM SECRET',1006,None,None,1,0),
            (8,'owner-dm','assistant','Not a visible final message',1007,'[{"name":"tool"}]',None,1,0),
            (9,'owner-dm','user','Compacted original fact',1008,None,None,0,1),
            (10,'owner-dm','user','Rewound fact',1009,None,None,0,0),
            (11,'cli','user','CLI SECRET',1010,None,None,1,0),
            (12,'unknown','user','UNOWNED SECRET',1011,None,None,1,0),
            (13,'owner-dm','user','\x00json:'+json.dumps([{'type':'text','text':'Visible screenshot caption'},{'type':'image_url','image_url':{'url':'SECRET IMAGE URL'}},{'type':'reasoning','text':'SECRET REASONING'}]),1012,None,None,1,0)])


def test_history_filters_synthetic_and_proven_replays_preserving_real_repeats(tmp_path,bridge):
    plugin_module()
    from tested_hermes_bridge.sync import read_history_batch,SYNTHETIC_PREFIXES
    from app.telegram_bridge import HistoryBatch
    original_history(tmp_path)
    with sqlite3.connect(tmp_path/'state.db') as db:
        db.execute('UPDATE messages SET active=0,compacted=1 WHERE id IN (1,2)')
        rows=[(20,'user',SYNTHETIC_PREFIXES[0]+' internal',2000),
              (21,'user','Visible appointment reference',2000.00001),
              (22,'assistant','Visible answer',2000.00002),
              (23,'user',SYNTHETIC_PREFIXES[2]+' internal',2000.00003),
              (24,'user','Compacted original fact',1008),
              (25,'user','Visible appointment reference',2005),
              (26,'assistant','Visible answer',2006),
              (27,'assistant',SYNTHETIC_PREFIXES[1]+' internal',3000)]
        db.executemany("INSERT INTO messages(id,session_id,role,content,timestamp) VALUES(?,'owner-dm',?,?,?)",rows)
    before=(tmp_path/'state.db').read_bytes()
    result=read_history_batch(tmp_path,'1234',0)
    assert [r['source_id'] for r in result['messages']]==[1,2,9,13,25,26]
    assert result['cursor']==27
    assert (tmp_path/'state.db').read_bytes()==before
    # Even an older client cannot inject known internal context into the home.
    rejected=[{'source_id':100+i,'session_id':'owner-dm','role':'user','content':prefix+' internal','timestamp':4000} for i,prefix in enumerate(SYNTHETIC_PREFIXES)]
    assert bridge.import_history(HistoryBatch(source_owner='1234',messages=rejected))['imported']==0


def test_original_history_reader_strict_owner_and_visible_content(tmp_path):
    plugin_module()
    from tested_hermes_bridge.sync import read_history_batch
    original_history(tmp_path)
    before=(tmp_path/'state.db').read_bytes()
    batch=read_history_batch(tmp_path,'1234',0)
    assert [row['source_id'] for row in batch['messages']]==[1,2,9,13]
    assert batch['messages'][0]['timestamp']==1000.25
    combined=json.dumps(batch)
    assert 'SECRET' not in combined and 'chain of thought' not in combined and 'Rewound' not in combined
    assert batch['messages'][-1]['content']=='Visible screenshot caption'
    assert (tmp_path/'state.db').read_bytes()==before
    assert read_history_batch(tmp_path,'unknown-owner',0)['messages']==[]


def test_history_import_dedup_updates_timestamp_and_no_tasks(bridge,tmp_path):
    plugin_module()
    from tested_hermes_bridge.sync import read_history_batch
    original_history(tmp_path)
    rows=read_history_batch(tmp_path,'1234',0)['messages']
    payload=HistoryBatch(source_owner='1234',messages=rows)
    first=bridge.import_history(payload)
    assert first['imported']==4 and first['updated']==0
    assert bridge.import_history(payload)['imported']==0
    assert bridge.store.list_tasks('1234')==[] and not bridge.tasks.submitted
    messages=bridge.messenger.list_messages('1234',first['conversation_id'])
    assert len(messages)==4 and messages[0]['created_at']==1000
    assert messages[0]['metadata']['source_timestamp']==1000.25
    assert messages[0]['metadata']['telegram_message_id']==1
    rows[0]['content']='Corrected appointment reference'
    assert bridge.import_history(HistoryBatch(source_owner='1234',messages=rows))['updated']==1
    again=bridge.messenger.list_messages('1234',first['conversation_id'])
    assert len(again)==4 and again[0]['id']==messages[0]['id']
    with pytest.raises(APIError): bridge.import_history(HistoryBatch(source_owner='other',messages=rows))
    assert bridge.store.list_agents('other')==[]
    with pytest.raises(ValidationError): HistoryBatch(source_owner='1234',messages=[{**rows[0],'role':'tool'}])


def test_history_search_and_exact_reads_only_visible_owner_messages(bridge):
    row={'source_id':1,'session_id':'private-dm','role':'user','content':'Archive exact phrase '+('x'*13000),'timestamp':1000.5}
    imported=bridge.import_history(HistoryBatch(source_owner='1234',messages=[row]))
    other=bridge.store.create_agent('foreign',name='Other',model='test',instructions='')
    home=bridge.messenger.home('foreign',other['id'])
    foreign=bridge.messenger.send('foreign',home['id'],'Archive exact phrase foreign')
    with bridge.store.db.transaction() as db:
        db.execute("INSERT INTO messages(id,conversation_id,user_id,role,content,status,created_at) VALUES('hidden-tool',?,'1234','tool','Archive exact phrase tool','completed',1001)",(imported['conversation_id'],))
    results=bridge.search_history(HistoryQuery(query='Archive exact phrase'))['matches']
    assert len(results)==1
    found=bridge.search_history(HistoryQuery(message_id=results[0]['id']))['message']
    assert len(found['content'])==12000 and found['next_offset']==12000
    assert found['source']=={'kind':'telegram','session_id':'private-dm','message_id':1,'timestamp':1000.5}
    tail=bridge.search_history(HistoryQuery(message_id=results[0]['id'],offset=found['next_offset']))['message']
    assert found['content']+tail['content']==row['content'] and tail['next_offset'] is None
    for forbidden in ['hidden-tool',foreign['message']['id']]:
        with pytest.raises(APIError): bridge.search_history(HistoryQuery(message_id=forbidden))


def test_history_sync_cursor_advances_only_after_commit_and_owner_change_resets(tmp_path,bridge):
    plugin_module()
    from tested_hermes_bridge.sync import sync_history
    original_history(tmp_path)
    config={'owner_id':'1234'}
    def broken(endpoint,payload,config): raise RuntimeError('Network unavailable')
    with pytest.raises(RuntimeError): sync_history(config,tmp_path,request=broken)
    checkpoint=tmp_path/'bot-mode-history-cursor.json'
    assert not checkpoint.exists()
    def lose_response(endpoint,payload,config):
        bridge.import_history(HistoryBatch(**payload))
        raise RuntimeError('Response lost after commit')
    with pytest.raises(RuntimeError): sync_history(config,tmp_path,request=lose_response)
    assert not checkpoint.exists()
    def accept(endpoint,payload,config):
        assert endpoint=='history/import'
        return bridge.import_history(HistoryBatch(**payload))
    result=sync_history(config,tmp_path,request=accept)
    assert result['imported']==0 and json.loads(checkpoint.read_text())['cursor']==13
    assert len(bridge.search_history(HistoryQuery(query='Visible'))['matches'])==3
    def other_owner(endpoint,payload,config):
        assert payload['source_owner']=='other'
        assert [row['source_id'] for row in payload['messages']]==[3]
        return {'imported':1,'updated':0}
    assert sync_history({'owner_id':'other'},tmp_path,request=other_owner)['imported']==1


def test_missing_and_old_history_database_are_safe(tmp_path):
    plugin_module()
    from tested_hermes_bridge.sync import sync_history,read_history_batch
    assert sync_history({'owner_id':'1234'},tmp_path)['available'] is False
    assert not (tmp_path/'state.db').exists()
    with sqlite3.connect(tmp_path/'state.db') as db:
        db.execute('CREATE TABLE sessions(id TEXT)')
    assert read_history_batch(tmp_path,'1234',0)['reason']=='history_schema_unavailable'

