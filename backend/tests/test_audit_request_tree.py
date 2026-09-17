"""Independent integration regression gates from the final source audit."""
import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.contracts import RuntimeEvent, RuntimeStatus
from app.db import Database
from app.history import History
from app.messenger import Messenger
from app.store import Store
from app.tasks import TaskManager
from app.workspace import Workspace


@pytest.fixture
def env(tmp_path):
    settings = Settings(database_path=tmp_path/'db.sqlite', workspace_root=tmp_path/'workspace')
    store = Store(Database(settings.database_path))
    messenger = Messenger(store)
    agents = [store.create_agent('owner', name=name, instructions='', model='test') for name in ('Chief','Peer','Helper')]
    group = messenger.create_group('owner', 'Group', [a['id'] for a in agents[:2]], agents[0]['id'])
    return store, messenger, agents, group, Workspace(settings)


@pytest.mark.asyncio
async def test_stop_marks_group_roots_and_child_before_first_runtime_await(env):
    store, messenger, agents, group, workspace = env
    request = messenger.send('owner',group['id'],'Do work',mention_agent_ids=[a['id'] for a in agents[:2]],client_request_id='audit-group')
    child = messenger.delegate('owner',request['task']['id'],agents[2]['id'],'Bounded helper')['task']
    ids = [t['id'] for t in request['tasks']] + [child['id']]
    seen = []
    async def cancel(task_id):
        assert all(store.get_task('owner',tid)['status']=='cancelled' for tid in ids)
        seen.append(task_id)
        await asyncio.sleep(0)
    manager = TaskManager(store,workspace,SimpleNamespace(cancel=cancel),messenger=messenger)
    await manager.cancel('owner',request['tasks'][1]['id'])
    assert set(seen)==set(ids)
    assert all(len([e for e in store.list_task_events('owner',tid) if e['event_type']=='task.cancelled'])==1 for tid in ids)
    await manager.cancel('owner',child['id'])
    assert len(seen)==len(ids)


@pytest.mark.asyncio
async def test_completed_parent_stop_still_cancels_running_helper(env):
    store, messenger, agents, group, workspace = env
    request = messenger.send('owner',group['id'],'Do work',client_request_id='audit-terminal')
    child = messenger.delegate('owner',request['task']['id'],agents[2]['id'],'Bounded helper')['task']
    store.finish_task(request['task']['id'],status='completed')
    manager = TaskManager(store,workspace,SimpleNamespace(),messenger=messenger)
    await manager.cancel('owner',request['task']['id'])
    assert store.get_task('owner',request['task']['id'])['status']=='completed'
    assert store.get_task('owner',child['id'])['status']=='cancelled'


@pytest.mark.asyncio
async def test_cancelled_worker_persists_partial_text(env):
    store, messenger, agents, group, workspace = env
    entered = asyncio.Event()
    class Runtime:
        def status(self):
            return RuntimeStatus(available=True)
        async def run_turn(self, request):
            yield RuntimeEvent('assistant.delta', {'text':'Partial answer'})
            entered.set()
            await asyncio.Event().wait()
        async def cancel(self, task_id):
            await asyncio.sleep(0)
    manager = TaskManager(store,workspace,Runtime(),messenger=messenger,history=History(store,messenger))
    request = messenger.send('owner',group['id'],'Do work',client_request_id='audit-partial')
    task_id = request['task']['id']
    manager.submit('owner',task_id)
    await asyncio.wait_for(entered.wait(),2)
    await manager.cancel('owner',task_id)
    await asyncio.sleep(0)
    messages = messenger.list_messages('owner',group['id'])
    assert any(m['content']=='Partial answer' and m['status']=='partial' for m in messages)
    assert store.get_task('owner',task_id)['status']=='cancelled'

def test_create_bot_reuse_does_not_disclose_colleague_private_instructions(env):
    from app.orchestration import Orchestration
    store, messenger, agents, group, workspace = env
    store.update_agent('owner',agents[2]['id'],{'instructions':'PRIVATE: customer account strategy'})
    request = messenger.send('owner',group['id'],'Find a specialist',client_request_id='audit-bot-privacy')
    service = Orchestration(store,messenger,'test')
    result = service.create_bot('owner',request['task']['id'],'Helper','Do harmless work')
    assert result['agent']['id']==agents[2]['id']
    assert 'instructions' not in result['agent']

@pytest.mark.asyncio
async def test_scheduled_crash_claim_is_skipped_after_schedule_edit(env):
    from app.routines import Routines
    store, messenger, agents, group, workspace = env
    submitted = []
    routines = Routines(store,messenger,SimpleNamespace(submit=lambda user,task: submitted.append(task)))
    item = routines.save('owner',agents[0]['id'],{'name':'Digest','instruction':'Old instruction','time':'09:00','timezone':'Europe/London','weekdays':[0,1,2,3,4,5,6]})
    original = messenger.send
    def crash(*args, **kwargs):
        raise RuntimeError('Simulated crash after durable claim')
    messenger.send = crash
    with pytest.raises(RuntimeError):
        routines.run('owner',item['id'],occurrence='scheduled:100')
    messenger.send = original
    routines.save('owner',agents[0]['id'],{'instruction':'New instruction'},item['id'])
    await routines.tick()
    assert not submitted
    with store.db.read() as db:
        claim = db.execute('SELECT status,task_id FROM routine_occurrences WHERE routine_id=?',(item['id'],)).fetchone()
    assert claim['status']=='skipped'


def test_manual_crash_retry_preserves_original_payload_after_edit(env):
    from app.routines import Routines
    store, messenger, agents, group, workspace = env
    routines = Routines(store,messenger,SimpleNamespace(submit=lambda *args: None))
    item = routines.save('owner',agents[0]['id'],{'name':'Digest','instruction':'Original instruction','time':'09:00','timezone':'Europe/London','weekdays':[0,1,2,3,4,5,6]})
    original = messenger.send
    def crash(*args, **kwargs):
        raise RuntimeError('Simulated crash after durable claim')
    messenger.send = crash
    with pytest.raises(RuntimeError):
        routines.run('owner',item['id'],client_request_id='same-click')
    messenger.send = original
    routines.save('owner',agents[0]['id'],{'instruction':'Changed instruction'},item['id'])
    result = routines.run('owner',item['id'],client_request_id='same-click')
    messages = messenger.list_messages('owner',result['task']['conversation_id'])
    assert messages[-1]['content']=='Routine: Digest\n\nOriginal instruction'


def test_dst_gap_and_repeated_hour_run_once():
    from datetime import datetime, timezone
    from app.routines import next_due
    def stamp(text):
        return int(datetime.fromisoformat(text).timestamp())
    assert next_due(stamp('2026-03-29T00:00:00+00:00'),'01:30','Europe/London',list(range(7)))==stamp('2026-03-29T01:00:00+00:00')
    first = next_due(stamp('2026-10-24T23:00:00+00:00'),'01:30','Europe/London',list(range(7)))
    assert first==stamp('2026-10-25T00:30:00+00:00')
    assert next_due(first,'01:30','Europe/London',list(range(7)))==stamp('2026-10-26T01:30:00+00:00')

@pytest.mark.asyncio
async def test_manual_compaction_holds_thread_lock_until_completion(tmp_path):
    import json
    from app.codex_runtime import CodexRuntime
    runtime = CodexRuntime(tmp_path/'runtime')
    key = json.dumps(['owner','chat','bot'],separators=(',',':'))
    runtime.db.execute('INSERT INTO threads(conversation,thread) VALUES(?,?)',(key,'thread'))
    runtime.db.commit()
    started = asyncio.Event()
    async def rpc(method,params,**kwargs):
        assert method=='thread/compact/start'
        started.set()
        return {}
    runtime.rpc=rpc
    operation = asyncio.create_task(runtime.compact('chat','owner','bot'))
    await asyncio.wait_for(started.wait(),1)
    await asyncio.sleep(0)
    assert not operation.done()
    assert runtime.locks[key].locked()
    await runtime.queues['thread'].put(('turn/completed',{'turn':{'status':'completed'}}))
    await asyncio.wait_for(operation,1)
    assert not runtime.locks[key].locked()
    runtime.db.close()


@pytest.mark.asyncio
async def test_one_root_capacity_still_allows_helper_progress(tmp_path):
    from app.codex_runtime import CodexRuntime
    from app.contracts import TurnRequest
    runtime = CodexRuntime(tmp_path/'runtime',max_concurrent=1)
    runtime.proc=SimpleNamespace(returncode=None)
    runtime.account={'type':'chatgpt'}
    runtime.models=[{'model':'test'}]
    entered=asyncio.Event()
    thread_ids=[]
    async def start():
        pass
    async def rpc(method,params,**kwargs):
        if method=='thread/start':
            tid='thread-'+str(len(thread_ids))
            thread_ids.append(tid)
            return {'thread':{'id':tid}}
        if method=='turn/start':
            tid=params['threadId']
            if tid==thread_ids[0]:
                entered.set()
            else:
                await runtime.queues[tid].put(('turn/completed',{'turn':{'status':'completed'}}))
                await runtime.queues[thread_ids[0]].put(('turn/completed',{'turn':{'status':'completed'}}))
            return {'turn':{'id':'turn-'+tid}}
        raise AssertionError(method)
    runtime.start=start
    runtime.rpc=rpc
    async def run(request):
        return [event async for event in runtime.run_turn(request)]
    parent=TurnRequest('parent','owner','group','chief','test','Policy',[{'role':'user','content':'Work'}])
    helper=TurnRequest('helper','owner','internal','helper','test','Helper policy',[{'role':'user','content':'Bounded work'}],metadata={'parent_task_id':'parent'})
    waiting=asyncio.create_task(run(parent))
    await asyncio.wait_for(entered.wait(),1)
    await asyncio.wait_for(run(helper),1)
    await asyncio.wait_for(waiting,1)
    assert len(set(thread_ids))==2
    runtime.db.close()

