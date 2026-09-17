"""Extension broker regressions using real adapters over mock HTTP transports."""
from __future__ import annotations
import asyncio
import base64
import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.config import Settings
from app.connection_provider import ConnectionProvider
from app.contracts import TurnRequest
from app.db import Database
from app.errors import APIError
from app.extension_service import Extensions
from app.messenger import Messenger
from app.store import Store


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('COMPOSIO_API_KEY', 'fixture-composio-key')
    settings=Settings(database_path=tmp_path/'db.sqlite',workspace_root=tmp_path/'files',session_secret='fixture-session',public_base_url='https://hermes.example')
    store=Store(Database(settings.database_path))
    messenger=Messenger(store)
    class Tasks:
        def __init__(self): self.submitted=[]
        def submit(self,user,task): self.submitted.append(task)
    tasks=Tasks()
    extension=Extensions(store,messenger,tasks,settings)
    agent=store.create_agent('owner',name='Chief',model='test',instructions='Help')
    home=messenger.home('owner',agent['id'])
    sent=messenger.send('owner',home['id'],'Do authorized work')
    request=TurnRequest(sent['task']['id'],'owner',home['id'],agent['id'],'test','Help')
    state={'schema':{'type':'object','properties':{'body':{'type':'string'}},'required':['body'],'additionalProperties':False},
           'executions':[], 'sessions':[], 'result':{'data':{'ok':True},'error':None},'gate':None,
           'accounts':[{'id':'account-one','toolkit':{'slug':'MAIL'},'user_id':extension.provider_user('owner'),'status':'ACTIVE','alias':'My mailbox','created_at':'2026-01-01'}],
           'linked_account':'account-new','callback':None,'slug':'MAIL_SEND'}
    async def transport(req):
        path=req.url.path
        if path.endswith('/connected_accounts'):
            return httpx.Response(200,json={'items':state['accounts']})
        if path.endswith('/session'):
            state['sessions'].append(json.loads(req.content))
            return httpx.Response(201,json={'session_id':'session-one'})
        if path.endswith('/search'):
            return httpx.Response(200,json={'tool_schemas':{state['slug']:{'tool_slug':state['slug'],'toolkit':'MAIL','input_schema':state['schema'],'hasFullSchema':True}}})
        if path.endswith('/execute'):
            state['executions'].append(json.loads(req.content))
            if state['gate']: await state['gate'].wait()
            if state.get('timeout'): raise httpx.ReadTimeout('encoded confidential detail',request=req)
            return httpx.Response(200,json=state['result'])
        if path.endswith('/link'):
            state['callback']=json.loads(req.content)['callback_url']
            return httpx.Response(200,json={'redirect_url':'https://connect.composio.dev/link','connected_account_id':state['linked_account']})
        if req.method=='DELETE': return httpx.Response(200,json={})
        raise AssertionError(path)
    extension.connection_factory=lambda key: ConnectionProvider(key,transport=httpx.MockTransport(transport))
    return extension,request,state


async def proposal(env, arguments=None):
    e,request,state=env
    await e.search_tools('owner','Send mail')
    return await e.propose_action(request,{'tool_slug':state['slug'],'account_id':'account-one','arguments':arguments or {'body':'Reviewed content'},'purpose':'Send the approved note'})


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['error','timeout','nested'])
async def test_private_failures_never_report_success_or_leak_or_retry(env,failure):
    e,request,state=env
    secret='PRIVATE-PAYLOAD-unique'
    encoded=base64.b64encode(secret.encode()).decode()
    field=e.private.save('owner',request.agent_id,label='Private note',purpose='Approved message body',value=secret)
    card=await proposal(env,{'body':{'$private':field['id']}})
    state['result']={'data':{},'error':encoded}
    if failure=='timeout': state['timeout']=True
    if failure=='nested': state['result']={'data':{'successful':False,'error':encoded},'error':None}
    result=await e.decide('owner',card['id'],'approve')
    assert result['status']=='uncertain'
    assert result['result']=={}
    assert len(state['executions'])==1
    assert state['executions'][0]['arguments']['body']==secret
    await e.decide('owner',card['id'],'approve')
    assert len(state['executions'])==1
    with e.store.db.read() as db:
        persisted=' '.join(str(tuple(row)) for table in ['chat_requests','messages','memory_entries','task_events'] for row in db.execute(f'SELECT * FROM {table}'))
        assert db.execute('SELECT state FROM private_fields WHERE id=?',(field['id'],)).fetchone()[0]=='quarantined'
    assert secret not in persisted and encoded not in persisted


@pytest.mark.asyncio
async def test_private_success_withholds_entire_provider_response(env):
    e,request,state=env
    secret='PRIVATE-SUCCESS-unique'
    encoded=base64.b64encode(secret.encode()).decode()
    field=e.private.save('owner',request.agent_id,label='Private note',purpose='Reviewed use',value=secret)
    card=await proposal(env,{'body':{'$private':field['id']}})
    state['result']={'data':{'encoded':encoded,'partial':secret[:12]},'error':None}
    result=await e.decide('owner',card['id'],'approve')
    assert result['status']=='completed' and result['result']['private_values_used']
    assert state['sessions'][-1]['connected_accounts']=={'mail':['account-one']}
    assert 'account' not in state['executions'][-1]
    assert encoded not in json.dumps(result) and secret[:12] not in json.dumps(result)
    e.store.finish_task(request.task_id,status='completed')
    followup=e.continue_request('owner',card['id'])
    assert encoded not in followup['message']['content']
    with pytest.raises(APIError): e.private.metadata('owner',request.agent_id,field['id'])


@pytest.mark.asyncio
async def test_schema_changes_expire_approval_before_dispatch(env):
    e,request,state=env
    card=await proposal(env)
    state['schema']['properties']['body']['maxLength']=3
    with pytest.raises(APIError,match='service action changed'):
        await e.decide('owner',card['id'],'approve')
    assert not state['executions']
    assert e.get_request('owner',card['id'])['status']=='expired'


@pytest.mark.asyncio
async def test_predispatch_validation_releases_one_time_private_value(env):
    e,request,state=env
    state['schema']['properties']['body']={'type':'integer'}
    field=e.private.save('owner',request.agent_id,label='Private number',purpose='Reviewed use',value='not-a-number')
    card=await proposal(env,{'body':{'$private':field['id']}})
    result=await e.decide('owner',card['id'],'approve')
    assert result['status']=='failed' and not state['executions']
    assert e.private.metadata('owner',request.agent_id,field['id'])['id']==field['id']


@pytest.mark.asyncio
async def test_approval_claim_is_once_under_concurrent_clicks(env):
    e,request,state=env
    card=await proposal(env)
    state['gate']=asyncio.Event()
    first=asyncio.create_task(e.decide('owner',card['id'],'approve'))
    for _ in range(100):
        if state['executions']: break
        await asyncio.sleep(0)
    assert state['executions']
    assert (await e.decide('owner',card['id'],'approve'))['status']=='executing'
    state['gate'].set()
    assert (await first)['status']=='completed'
    assert len(state['executions'])==1


@pytest.mark.asyncio
async def test_account_identity_change_and_private_scope_rejected(env):
    e,request,state=env
    card=await proposal(env)
    state['accounts'][0]['alias']='Different mailbox'
    with pytest.raises(APIError,match='account changed'): await e.decide('owner',card['id'],'approve')
    assert not state['executions']
    other=e.store.create_agent('owner',name='Other',model='test',instructions='')
    field=e.private.save('owner',other['id'],label='Private',purpose='Other bot only',value='not-for-chief')
    with pytest.raises(APIError): await proposal(env,{'body':{'$private':field['id']}})
    with pytest.raises(APIError): e.get_request('stranger',card['id'])


@pytest.mark.asyncio
async def test_oauth_callback_requires_linked_account_owner_not_existing_toolkit(env):
    e,request,state=env
    await e.link('owner','MAIL')
    token=parse_qs(urlsplit(state['callback']).query)['state'][0]
    with pytest.raises(APIError,match='not complete'): await e.callback('owner',token)
    state['accounts'].append({**state['accounts'][0],'id':'account-new','user_id':e.provider_user('stranger')})
    with pytest.raises(APIError): await e.callback('owner',token)
    state['accounts'][-1]['user_id']=e.provider_user('owner')
    with pytest.raises(APIError): await e.callback('stranger',token)
    await e.callback('owner',token)
    with pytest.raises(APIError): await e.callback('owner',token)


@pytest.mark.asyncio
async def test_remote_schema_references_and_generic_api_actions_rejected(env):
    e,request,state=env
    state['schema']={'$ref':'http://127.0.0.1/private'}
    with pytest.raises(APIError): await proposal(env)
    state['schema']={'type':'object'}
    state['slug']='MAIL_CUSTOM_API_CALL'
    with pytest.raises(APIError): await proposal(env)
    assert not state['executions']


@pytest.mark.asyncio
async def test_expired_and_restarted_intents_cannot_dispatch(env):
    e,request,state=env
    card=await proposal(env)
    with e.store.db.transaction() as db:
        db.execute('UPDATE chat_requests SET expires_at=1 WHERE id=?',(card['id'],))
    assert (await e.decide('owner',card['id'],'approve'))['status']=='expired'
    assert not state['executions']
    field=e.private.save('owner',request.agent_id,label='Private',purpose='Reviewed use',value='secret-before-restart')
    next_card=await proposal(env,{'body':{'$private':field['id']}})
    with e.store.db.transaction() as db:
        db.execute("UPDATE chat_requests SET status='executing' WHERE id=?",(next_card['id'],))
    e.private.claim('owner',request.agent_id,{field['id']:field['revision']},next_card['id'])
    restarted=Extensions(e.store,e.messenger,e.tasks,e.settings)
    assert (await restarted.decide('owner',next_card['id'],'approve'))['status']=='uncertain'
    with e.store.db.read() as db:
        assert db.execute('SELECT state FROM private_fields WHERE id=?',(field['id'],)).fetchone()[0]=='quarantined'
    assert not state['executions']


@pytest.mark.asyncio
async def test_deleted_private_reference_invalidates_dispatch(env):
    e,request,state=env
    field=e.private.save('owner',request.agent_id,label='Private',purpose='Reviewed use',value='deleted-private-value')
    card=await proposal(env,{'body':{'$private':field['id']}})
    e.private.delete('owner',request.agent_id,field['id'])
    result=await e.decide('owner',card['id'],'approve')
    assert result['status']=='failed' and not state['executions']


def test_lost_vault_key_is_not_silently_regenerated(env):
    e,request,state=env
    from app.private_fields import PrivateFields
    e.private.save('owner',request.agent_id,label='Private',purpose='Reviewed use',value='encrypted-content')
    e.private.key_path.unlink()
    reopened=PrivateFields(e.store,e.private.key_path)
    assert not reopened.available
    assert not e.private.key_path.exists()


def test_teaching_screenshots_are_attached_and_verification_is_revision_bound(env):
    e,request,state=env
    file=e.store.create_file('owner',agent_id=request.agent_id,relative_path='demo.png',size=10,sha256='0'*64,content_type='image/png')
    teaching=e.teachings.save('owner',request.agent_id,{'name':'Invoice check','trigger':'invoice','steps':['Read invoice','Check totals'],'frame_file_ids':[file['id']]})
    with pytest.raises(APIError): e.teachings.save('owner',request.agent_id,{'verified':True},teaching['id'])
    run=e.teachings.run('owner',request.agent_id,teaching['id'],'Check this invoice','run-1')
    assert run['message']['metadata']['attachments'][0]['file_id']==file['id']
    assert e.teachings.run('owner',request.agent_id,teaching['id'],'Check this invoice','run-1')['task']['id']==run['task']['id']
    with pytest.raises(APIError): e.teachings.save('owner',request.agent_id,{'verified':True},teaching['id'])
    e.store.finish_task(run['task']['id'],status='completed')
    assert e.teachings.save('owner',request.agent_id,{'verified':True},teaching['id'])['status']=='verified'
    draft=e.teachings.save('owner',request.agent_id,{'steps':['Unproven changed steps']},teaching['id'])
    assert draft['status']=='unverified' and draft['revision']==2
    failed=e.teachings.run('owner',request.agent_id,teaching['id'],'Try new version','run-2')
    e.store.finish_task(failed['task']['id'],status='failed')
    with pytest.raises(APIError): e.teachings.save('owner',request.agent_id,{'verified':True},teaching['id'])
    recalled=e.teachings.context('owner',request.agent_id,'invoice')[0]
    assert recalled['instructions']=='Read invoice\nCheck totals'
    assert 'version 1' in recalled['evidence']

