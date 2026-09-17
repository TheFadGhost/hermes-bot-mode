from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.db import Database
from app.errors import APIError
from app.messenger import Messenger
from app.store import Store


def setup_store(tmp_path):
    store = Store(Database(tmp_path / "messenger.sqlite"))
    messenger = Messenger(store)
    user = "owner"
    agents = [
        store.create_agent(user, name=name, instructions=name, model="gpt-5.6-luna")
        for name in ("Chief", "Scout", "Writer")
    ]
    return store, messenger, user, agents


def test_home_aggregates_legacy_aliases_with_stable_cursor(tmp_path):
    store, messenger, user, agents = setup_store(tmp_path)
    first = store.create_conversation(user, agents[0]["id"], "old")
    second = store.create_conversation(user, agents[0]["id"], "new")
    store.create_message_and_task(user, first["id"], "legacy one")
    second_message, _, _ = store.create_message_and_task(user, second["id"], "legacy two")
    home = messenger.home(user, agents[0]["id"])
    assert set(messenger.scope_ids(user, second["id"])) == {first["id"], second["id"]}
    page = messenger.list_messages(user, home["id"], limit=1)
    assert page[0]["content"] == "legacy two"
    older = messenger.list_messages(user, home["id"], limit=1, before_id=page[0]["id"])
    assert older[0]["content"] == "legacy one"
    assert messenger.exact_message(user, home["id"], str(second_message["id"]))["content"] == "legacy two"
    with pytest.raises(APIError):
        messenger.list_messages("other", home["id"])


def test_send_is_atomic_and_idempotent_under_race(tmp_path):
    store, messenger, user, agents = setup_store(tmp_path)
    home = messenger.home(user, agents[0]["id"])

    def send_once():
        return messenger.send(user, home["id"], "same", client_request_id="retry-key")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: send_once(), range(8)))
    assert {item["message"]["id"] for item in results} == {results[0]["message"]["id"]}
    assert sum(not item["replayed"] for item in results) == 1
    assert len(messenger.list_messages(user, home["id"])) == 1
    with pytest.raises(APIError) as error:
        messenger.send(user, home["id"], "changed", client_request_id="retry-key")
    assert error.value.code == "idempotency_conflict"


def test_group_mentions_membership_and_explicit_file_grants(tmp_path):
    store, messenger, user, agents = setup_store(tmp_path)
    group = messenger.create_group(user, "Review", [item["id"] for item in agents[:2]], agents[0]["id"])
    coordinator_file = store.create_file(user, agent_id=agents[0]["id"], relative_path="shared.txt", size=1, sha256="a" * 64, content_type="text/plain")
    scout_file = store.create_file(user, agent_id=agents[1]["id"], relative_path="private.txt", size=1, sha256="b" * 64, content_type="text/plain")
    result = messenger.send(
        user,
        group["id"],
        "review",
        mention_agent_ids=[agents[1]["id"]],
        file_ids=[coordinator_file["id"]],
        client_request_id="group-1",
    )
    assert [task["agent_id"] for task in result["tasks"]] == [agents[1]["id"]]
    assert messenger.file_allowed(user, agents[1]["id"], group["id"], coordinator_file["id"])
    with pytest.raises(APIError) as error:
        messenger.send(user, group["id"], "private", file_ids=[scout_file["id"]], client_request_id="group-2")
    assert error.value.code == "file_grant_required"
    messenger.grant_files(user, group["id"], [scout_file["id"]], granted_by_agent_id=agents[0]["id"])
    assert messenger.file_allowed(user, agents[0]["id"], group["id"], scout_file["id"])
    with pytest.raises(APIError):
        messenger.send("other", group["id"], "cross account")


def test_delegate_inherits_only_parent_attachments_and_relays_once(tmp_path):
    store, messenger, user, agents = setup_store(tmp_path)
    home = messenger.home(user, agents[0]["id"])
    item = store.create_file(user, agent_id=agents[0]["id"], relative_path="brief.txt", size=1, sha256="c" * 64, content_type="text/plain")
    root = messenger.send(user, home["id"], "delegate", file_ids=[item["id"]], client_request_id="root")
    child = messenger.delegate(user, root["task"]["id"], agents[1]["id"], "research")
    assert messenger.file_allowed(user, agents[1]["id"], child["conversation"]["id"], item["id"])
    assert messenger.request_task_ids(user, home["id"], root["request_id"]) == [root["task"]["id"], child["task"]["id"]]
    first = messenger.append_collaboration_message(user, home["id"], agents[1]["id"], "done", source_task_id=child["task"]["id"], request_id=root["request_id"])
    second = messenger.append_collaboration_message(user, home["id"], agents[1]["id"], "done", source_task_id=child["task"]["id"], request_id=root["request_id"])
    assert first == second

