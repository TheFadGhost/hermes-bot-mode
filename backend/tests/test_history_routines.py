import asyncio
import json
from datetime import datetime, timezone

import pytest

from app.db import Database
from app.store import Store
from app.messenger import Messenger
from app.history import History, RECENT_CHAR_BUDGET, RETRIEVAL_CHAR_BUDGET
from app.orchestration import Orchestration
from app.routines import Routines, next_due
from app.errors import APIError


def setup(tmp_path):
    store = Store(Database(tmp_path / "chat.sqlite"))
    messenger = Messenger(store)
    history = History(store,messenger)
    agent = store.create_agent("owner",name="Chief",instructions="Help",model="gpt-5.6-luna")
    home = messenger.home("owner",agent["id"])
    return store,messenger,history,agent,home


def test_long_archive_keeps_exact_sources_and_bounded_context(tmp_path):
    store,messenger,history,agent,home = setup(tmp_path)
    first = messenger.send("owner",home["id"],"My Edinburgh reservation reference is CALDER-4821.")
    for index in range(80):
        messenger.send("owner",home["id"],f"Unrelated note {index}: "+"x"*700)
    correction = messenger.send("owner",home["id"],"Correction: Edinburgh reservation is CALDER-9937, replacing CALDER-4821.")
    current = messenger.send("owner",home["id"],"What is my Edinburgh reservation reference?")
    future = messenger.send("owner",home["id"],"Edinburgh reservation future instruction must not enter an earlier task")
    recent,retrieval,metrics = history.prepare("owner",home["id"],agent["id"],current["task"]["id"],current["message"]["id"])
    assert metrics["recent_chars"]<=RECENT_CHAR_BUDGET
    assert len(retrieval)<=RETRIEVAL_CHAR_BUDGET
    assert first["message"]["id"] in metrics["source_ids"]
    assert correction["message"]["id"] in metrics["source_ids"]
    assert future["message"]["id"] not in metrics["source_ids"]
    assert recent[-1]["id"]==current["message"]["id"]
    assert history.read("owner",home["id"],[first["message"]["id"]])[0]["content"]==first["message"]["content"]
    assert len(messenger.list_messages("owner",home["id"],limit=1000))==84


def test_history_is_account_and_group_member_scoped(tmp_path):
    store,messenger,history,agent,home = setup(tmp_path)
    private = messenger.send("owner",home["id"],"Private secret strawberry address")
    other = store.create_agent("owner",name="Helper",instructions="Help",model="gpt-5.6-luna")
    with pytest.raises(APIError):
        history.search("owner",home["id"],"strawberry",agent_id=other["id"])
    with pytest.raises(APIError):
        history.read("stranger",home["id"],[private["message"]["id"]])
    otherhome = messenger.home("owner",other["id"])
    assert history.search("owner",otherhome["id"],"strawberry",agent_id=other["id"])==[]


def test_chief_bootstrap_is_idempotent_and_bot_creation_bounded(tmp_path):
    store,messenger,history,agent,home = setup(tmp_path)
    orchestration = Orchestration(store,messenger,"gpt-5.6-luna")
    first = orchestration.bootstrap("owner")
    assert first==orchestration.bootstrap("owner")
    assert first["chief"]["id"]==agent["id"]
    task = messenger.send("owner",home["id"],"Create specialists")["task"]
    one = orchestration.create_bot("owner",task["id"],"Researcher","Research carefully")
    assert one["agent"]["id"]==orchestration.create_bot("owner",task["id"],"Researcher","Research carefully")["agent"]["id"]
    for name in ("Writer","Planner"):
        orchestration.create_bot("owner",task["id"],name,"Help")
    with pytest.raises(APIError,match="three"):
        orchestration.create_bot("owner",task["id"],"Fourth","Help")
    store.cancel_task(task["id"])
    with pytest.raises(APIError):
        orchestration.create_bot("owner",task["id"],"Later","Help")


def stamp(value):
    return int(datetime.fromisoformat(value).timestamp())


def test_wall_clock_dst_gap_and_fold_once():
    gap = next_due(stamp("2026-03-29T00:00:00+00:00"),"01:30","Europe/London",[6])
    assert gap==stamp("2026-03-29T01:00:00+00:00")
    fold = next_due(stamp("2026-10-25T00:00:00+00:00"),"01:30","Europe/London",[6])
    assert fold==stamp("2026-10-25T00:30:00+00:00")
    assert next_due(fold,"01:30","Europe/London",[6])==stamp("2026-11-01T01:30:00+00:00")


def test_routines_idempotency_no_overlap_and_pause(tmp_path):
    store,messenger,history,agent,home = setup(tmp_path)
    submitted=[]
    class Tasks:
        def submit(self,user,task):
            submitted.append(task)
    routines=Routines(store,messenger,Tasks())
    item=routines.save("owner",agent["id"],dict(name="Briefing",instruction="Summarize today",time="08:00",timezone="Europe/London",weekdays=[0,1,2,3,4]))
    first=routines.run("owner",item["id"],client_request_id="one")
    again=routines.run("owner",item["id"],client_request_id="one")
    assert first["task"]["id"]==again["task"]["id"]
    with pytest.raises(APIError,match="already working"):
        routines.run("owner",item["id"],client_request_id="two")
    store.cancel_task(first["task"]["id"])
    routines.save("owner",agent["id"],{"enabled":False},item["id"])
    with pytest.raises(APIError):
        routines.run("owner",item["id"],occurrence="scheduled:1")
    assert routines.run("owner",item["id"],client_request_id="two")["task"]["id"]!=first["task"]["id"]
    routines.archive("owner",item["id"])
    assert routines.list("owner",agent["id"])==[]

