"""Regression cases for natural recall and explicit user corrections."""
from app.db import Database
from app.store import Store
from app.errors import APIError
import json
import pytest


def make_store(tmp_path):
    store = Store(Database(tmp_path / "memory.sqlite"))
    agent = store.create_agent("owner", name="Chief", model="test", instructions="Help")
    return store, agent["id"]


def save(store, agent_id, content, supersedes_id=None):
    return store.create_memory(
        "owner", scope="private", agent_id=agent_id,
        memory_key="Edinburgh reservation", content=content,
        source="chat:home:source", confidence=1.0, supersedes_id=supersedes_id,
    )


def test_natural_language_request_recalls_matching_fact(tmp_path):
    store, agent_id = make_store(tmp_path)
    memory = save(store, agent_id, "Edinburgh reservation reference is CALDER-4821.")
    recalled = store.search_memory("owner", "What is my Edinburgh reservation reference?", agent_id=agent_id)
    assert memory["id"] in [row["id"] for row in recalled]


def test_correction_retires_old_fact_from_recall_but_keeps_provenance(tmp_path):
    store, agent_id = make_store(tmp_path)
    old = save(store, agent_id, "Edinburgh reservation is CALDER-4821.")
    corrected = save(store, agent_id, "Edinburgh reservation is CALDER-9937.", old["id"])
    recalled = store.search_memory("owner", "Edinburgh", agent_id=agent_id)
    assert [row["id"] for row in recalled] == [corrected["id"]]
    assert store.get_memory("owner", old["id"], agent_id=agent_id)["content"] == old["content"]
    assert [row['id'] for row in store.list_memory('owner', agent_id=agent_id)] == [corrected['id']]


def test_corrections_cannot_cross_visibility_or_owner_or_create_cycles(tmp_path):
    store, agent_id = make_store(tmp_path)
    shared = store.create_memory('owner', scope='shared', agent_id=None, content='Edinburgh shared fact',
                                 memory_key='trip', source='user', confidence=1, supersedes_id=None)
    with pytest.raises(APIError, match='same memory scope'):
        save(store, agent_id, 'Private correction must not hide shared fact', shared['id'])
    other = store.create_agent('other', name='Other', model='test', instructions='')
    private = save(store, agent_id, 'Edinburgh private fact')
    with pytest.raises(APIError, match='same memory scope'):
        store.create_memory('other', scope='private', agent_id=other['id'], content='Invalid correction',
                            memory_key='trip', source='user', confidence=1, supersedes_id=private['id'])
    corrected = save(store, agent_id, 'Edinburgh corrected', private['id'])
    for replacement in (private['id'], corrected['id']):
        with pytest.raises(APIError, match='cycle'):
            store.update_memory('owner', private['id'], {'supersedes_id': replacement}, agent_id=agent_id)
    with pytest.raises(APIError, match='same memory scope'):
        store.update_memory('owner', private['id'], {'supersedes_id': shared['id']}, agent_id=agent_id)
    assert store.search_memory('owner', 'Edinburgh', scope='shared')[0]['id'] == shared['id']


def test_natural_recall_fallback_and_empty_query(tmp_path):
    store, agent_id = make_store(tmp_path)
    first = save(store, agent_id, 'Edinburgh reservation reference CALDER-4821')
    store.db.fts_available = False
    assert store.search_memory('owner', 'What is my Edinburgh reservation reference?', agent_id=agent_id)[0]['id'] == first['id']
    assert store.search_memory('owner', 'What is my?', agent_id=agent_id) == []


def test_memory_context_keeps_correction_provenance_and_valid_bounded_json():
    from app.tasks import TaskManager
    rows = [dict(id=index, scope='private', memory_key='trip', content='x' * 50000,
                 source='chat:home:message', supersedes_id=index-1, confidence=1, updated_at=123)
            for index in range(1, 20)]
    context = TaskManager._memory_context(rows)
    assert len(context) <= 24000
    parsed = json.loads(context)
    assert parsed[0]['id'] == 1
    assert parsed[0]['source'] == 'chat:home:message'
    assert parsed[0]['supersedes_id'] == 0


@pytest.mark.parametrize('padding', ['exact', 'trimmed', 'surrounding'])
def test_chief_bootstrap_upgrades_only_known_default(tmp_path, padding):
    from app.messenger import Messenger
    from app.orchestration import Orchestration, CHIEF_INSTRUCTIONS, LEGACY_CHIEF_INSTRUCTIONS
    store, agent_id = make_store(tmp_path)
    legacy = LEGACY_CHIEF_INSTRUCTIONS
    if padding == 'trimmed':
        legacy = legacy.strip()
    elif padding == 'surrounding':
        legacy = '\t\r\n  ' + legacy + '  \r\n\t'
    store.update_agent('owner', agent_id, {'instructions': legacy})
    orchestration = Orchestration(store, Messenger(store), 'test')
    upgraded = orchestration.bootstrap('owner')
    assert upgraded['chief']['instructions'] == CHIEF_INSTRUCTIONS
    assert upgraded['chief']['id'] == agent_id
    store.update_agent('owner', agent_id, {'instructions': 'My personal instructions'})
    assert orchestration.bootstrap('owner')['chief']['instructions'] == 'My personal instructions'
    customized = '\n' + LEGACY_CHIEF_INSTRUCTIONS.strip() + '\nAlways answer in Spanish.\n'
    store.update_agent('owner', agent_id, {'instructions': customized})
    assert orchestration.bootstrap('owner')['chief']['instructions'] == customized


def test_procedure_search_finds_older_match_before_bounded_limit(tmp_path):
    from app.learned_skills import LearnedSkills
    store, agent_id = make_store(tmp_path)
    conversation = store.create_conversation('owner', agent_id, 'Procedures')
    _, task, _ = store.create_message_and_task('owner', conversation['id'], 'Verified workflows')
    store.finish_task(task['id'], status='completed')
    skills = LearnedSkills(store)
    oldest = skills.propose('owner', agent_id, task['id'], name='Edinburgh reservation',
                            trigger='reservation itinerary', instructions='Read confirmation', evidence='Confirmed')
    with store.db.transaction() as db:
        db.execute('UPDATE learned_skills SET updated_at=1 WHERE id=?', (oldest['id'],))
        # Realistic stored collection: 200 newer ready procedures hide the older
        # matching entry under the former pre-filter limit.
        db.executemany('INSERT INTO learned_skills(id,user_id,agent_id,name,trigger,instructions,evidence,source_task_id,revision,state,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            [(f'new-{index}', 'owner', agent_id, f'Workflow {index}', 'routine workflow', 'Perform verified steps',
              'Observed success', task['id'], 1, 'ready', index+2) for index in range(200)])
    matches = skills.list('owner', agent_id, query='Edinburgh', enabled_only=True)
    assert [item['id'] for item in matches] == [oldest['id']]
    assert len(skills.list('owner', agent_id, enabled_only=True)) == 8
    assert len(skills.list('owner', agent_id)) == 200
    assert len(skills.list('owner', agent_id, query='workflow', enabled_only=True)) == 8
    colleague = store.create_agent('owner', name='Colleague', model='test', instructions='')
    assert skills.list('owner', colleague['id'], query='Edinburgh', enabled_only=True) == []
    with pytest.raises(APIError):
        skills.list('other-owner', agent_id, query='Edinburgh', enabled_only=True)
    skills.change('owner', agent_id, oldest['id'], enabled=False)
    assert skills.list('owner', agent_id, query='Edinburgh', enabled_only=True) == []


def test_memory_replacement_lookup_index_exists(tmp_path):
    store, _ = make_store(tmp_path)
    with store.db.transaction() as db:
        db.execute('DROP INDEX idx_memory_supersedes')
    store.db.migrate()
    with store.db.read() as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_memory_supersedes'").fetchone()

