import asyncio
from types import SimpleNamespace

from app.codex_runtime import CodexRuntime
from app.contracts import TurnRequest


def test_separate_member_threads_and_helper_progress_with_one_root_slot(tmp_path):
    async def scenario():
        runtime=CodexRuntime(tmp_path,max_concurrent=1)
        runtime.proc=SimpleNamespace(returncode=None)
        runtime.account={"type":"chatgpt"}
        runtime.models=[{"model":"gpt-5.6-luna"}]
        started=asyncio.Event()
        helper_done=asyncio.Event()
        threads=[]
        async def start(): pass
        async def rpc(method,params,timeout=45):
            if method=="thread/start":
                thread=f"thread-{len(threads)}"
                threads.append(thread)
                return {"thread":{"id":thread}}
            if method=="thread/resume":
                return {"thread":{"id":params["threadId"]}}
            if method=="turn/start":
                if params["input"][0]["text"]=="parent":
                    started.set()
                    await asyncio.wait_for(helper_done.wait(),1)
                else:
                    helper_done.set()
                await runtime.queues[params["threadId"]].put(("turn/completed",{"turn":{"status":"completed"}}))
                return {"turn":{"id":"turn"}}
            raise AssertionError(method)
        runtime.start=start
        runtime.rpc=rpc
        def request(task,agent,prompt,metadata=None):
            return TurnRequest(task,"owner","same-group",agent,"gpt-5.6-luna","Help",[{"role":"user","content":prompt}],metadata or {})
        async def run(req):
            return [event async for event in runtime.run_turn(req)]
        parent=asyncio.create_task(run(request("parent-task","chief","parent")))
        await started.wait()
        helper=asyncio.create_task(run(request("helper-task","researcher","helper",{"parent_task_id":"parent-task"})))
        await asyncio.wait_for(asyncio.gather(parent,helper),2)
        assert len(threads)==2
        await run(request("later","chief","followup"))
        assert len(threads)==2
        runtime.db.close()
    asyncio.run(scenario())

