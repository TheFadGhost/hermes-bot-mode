import asyncio

from app.config import Settings
from app.contracts import RuntimeEvent, RuntimeStatus
from app.db import Database
from app.store import Store
from app.messenger import Messenger
from app.history import History
from app.tasks import TaskManager
from app.workspace import Workspace
from app.scoped_tools import ScopedToolBridge


def test_group_tasks_use_actual_responder_and_shared_files_then_relay_helper(tmp_path):
    async def scenario():
        settings=Settings(database_path=tmp_path/"db.sqlite",workspace_root=tmp_path/"files")
        store=Store(Database(settings.database_path))
        messenger=Messenger(store)
        history=History(store,messenger)
        workspace=Workspace(settings)
        chief=store.create_agent("u",name="Chief",instructions="Chief policy",model="gpt-5.6-luna")
        scout=store.create_agent("u",name="Scout",instructions="Scout policy",model="gpt-5.6-luna")
        group=messenger.create_group("u","Trip",[chief["id"],scout["id"]])
        path=workspace.path_for("u",chief["id"],"shared.txt")
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text("Shared itinerary",encoding="utf-8")
        file=store.create_file("u",agent_id=chief["id"],relative_path="shared.txt",size=16,sha256="0"*64,content_type="text/plain")
        requests=[]
        class Runtime:
            def status(self): return RuntimeStatus(available=True)
            async def run_turn(self,request):
                requests.append(request)
                if request.metadata.get("file_attachments"):
                    read=await bridge.handle(request,"files_read",{"file_id":file["id"]})
                    assert read["content"]=="Shared itinerary"
                yield RuntimeEvent("assistant.delta",{"text":request.agent_id+" reply"})
                yield RuntimeEvent("turn.completed",{"status":"completed"})
        tasks=TaskManager(store,workspace,Runtime(),messenger=messenger,history=history)
        bridge=ScopedToolBridge(store,workspace,tasks)
        result=messenger.send("u",group["id"],"Review itinerary",file_ids=[file["id"]],mention_agent_ids=[chief["id"],scout["id"]],client_request_id="group-send")
        for task in result["tasks"]:
            await tasks._run("u",task["id"])
        assert {request.agent_id for request in requests}=={chief["id"],scout["id"]}
        assert {request.instructions for request in requests}=={"Chief policy","Scout policy"}
        assert all(store.get_task("u",task["id"])["status"]=="completed" for task in result["tasks"])
        messages=messenger.list_messages("u",group["id"])
        assert len(messages)==3
        assert {message["author_agent_id"] for message in messages if message["role"]=="assistant"}=={chief["id"],scout["id"]}
        parent=messenger.send("u",group["id"],"Ask Scout for another detail")
        child=messenger.delegate("u",parent["task"]["id"],scout["id"],"Research a detail")
        store.finish_task(parent["task"]["id"],status="completed")
        await tasks._run("u",child["task"]["id"])
        relays=[message for message in messenger.list_messages("u",group["id"]) if message.get("source_task_id")==child["task"]["id"]]
        assert len(relays)==1
        assert relays[0]["author_agent_id"]==scout["id"]
        assert relays[0]["content"]==scout["id"]+" reply"
        assert requests[-1].metadata["parent_task_id"]==parent["task"]["id"]
    asyncio.run(scenario())

