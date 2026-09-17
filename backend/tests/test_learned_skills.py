from pathlib import Path
import pytest

from app.config import Settings
from app.db import Database
from app.store import Store
from app.learned_skills import LearnedSkills
from app.errors import APIError
from app.workspace import Workspace
from app.scoped_tools import ScopedToolBridge


def setup(tmp_path):
    settings = Settings(database_path=tmp_path/'db.sqlite', workspace_root=tmp_path/'files')
    store = Store(Database(settings.database_path))
    a = store.create_agent('owner', name='A', model='gpt-5.6-luna', instructions='')
    b = store.create_agent('owner', name='B', model='gpt-5.6-luna', instructions='')
    c = store.create_conversation('owner', a['id'], 'Test')
    _, task, _ = store.create_message_and_task('owner', c['id'], 'Learn a procedure')
    return store, a, b, task, Workspace(settings)


def test_pending_procedure_requires_success_and_preserves_private_scope(tmp_path):
    store, a, b, task, _ = setup(tmp_path)
    skills = LearnedSkills(store)
    saved = skills.propose('owner', a['id'], task['id'], name='Check status', trigger='status check', instructions='Open the status page, read its status.', evidence='The page displayed operational.')
    assert saved['state'] == 'pending'
    assert skills.list('owner', a['id']) == []
    skills.finalize_task(task['id'], succeeded=True)
    assert skills.list('owner', a['id']) == []  # caller cannot mark unfinished work verified
    # First failed promotion discards; propose anew after a completed source task.
    store.finish_task(task['id'], status='completed')
    saved = skills.propose('owner', a['id'], task['id'], name='Check status', trigger='status check', instructions='Open the status page, read its status.', evidence='The page displayed operational.')
    assert skills.list('owner', a['id'], query='status', enabled_only=True)
    assert skills.list('owner', b['id']) == []
    with pytest.raises(APIError):
        skills.change('other-owner', a['id'], saved['id'], enabled=False)
    skills.change('owner', a['id'], saved['id'], enabled=False)
    assert skills.list('owner', a['id'], enabled_only=True) == []
    skills.change('owner', a['id'], saved['id'], delete=True)
    assert skills.list('owner', a['id']) == []


def test_failed_revision_does_not_replace_working_procedure(tmp_path):
    store, a, _, task, _ = setup(tmp_path)
    skills = LearnedSkills(store)
    values = dict(name='check', trigger='check status', instructions='Read status', evidence='Visible confirmation')
    store.finish_task(task['id'], status='completed')
    first = skills.propose('owner', a['id'], task['id'], **values)
    _, second_task, _ = store.create_message_and_task('owner', task['conversation_id'], 'New attempt')
    skills.propose('owner', a['id'], second_task['id'], **{**values, 'instructions':'Different steps'})
    store.finish_task(second_task['id'], status='failed')
    skills.finalize_task(second_task['id'], succeeded=False)
    assert skills.list('owner', a['id'])[0]['id'] == first['id']


def test_group_responder_learns_in_its_own_scope(tmp_path):
    from app.messenger import Messenger
    store, a, b, _, _ = setup(tmp_path)
    messenger = Messenger(store)
    group = messenger.create_group('owner', name='Team', agent_ids=[a['id'], b['id']], coordinator_id=a['id'])
    result = messenger.send('owner', group['id'], content='Learn this', mention_agent_ids=[b['id']], client_request_id='learn-b')
    task = result['tasks'][0]
    skills = LearnedSkills(store)
    values = dict(name='Check status', trigger='status', instructions='Read the status page.', evidence='Observed success.')
    skills.propose('owner', b['id'], task['id'], **values)
    with pytest.raises(APIError):
        skills.propose('owner', a['id'], task['id'], **values)
    store.finish_task(task['id'], status='completed')
    skills.finalize_task(task['id'], succeeded=True)
    assert len(skills.list('owner', b['id'])) == 1
    assert skills.list('owner', a['id']) == []


def test_utf8_chunks_round_trip_at_multibyte_boundary(tmp_path):
    store, a, _, _, workspace = setup(tmp_path)
    bridge = ScopedToolBridge(store, workspace)
    text = 'abc🐱deféghi日本語'
    workspace.path_for('owner', a['id'], 'unicode.txt').write_text(text, encoding='utf-8')
    result = []
    offset = 0
    while True:
        chunk = bridge._files_read('owner', a['id'], {'path':'unicode.txt','offset':offset,'limit':4})
        result.append(chunk['content'])
        if chunk['next_offset'] is None:
            break
        assert chunk['next_offset'] > offset
        offset = chunk['next_offset']
    assert ''.join(result) == text


def test_docx_extraction_and_archive_size_limit(tmp_path):
    import zipfile
    from app.document_reader import extract
    document = tmp_path/'test.docx'
    with zipfile.ZipFile(document, 'w') as archive:
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Hello document</w:t></w:r></w:p></w:document>')
    assert extract(document)['text'] == 'Hello document'
    with zipfile.ZipFile(document, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml', 'x' * (4*1024*1024+1))
    with pytest.raises(ValueError):
        extract(document)


def test_disabled_preference_survives_pending_revision_and_dedup_is_task_bound(tmp_path):
    store, a, _, task, _ = setup(tmp_path)
    skills = LearnedSkills(store)
    values = dict(name='check', trigger='status check', instructions='Read status', evidence='Observed successful status')
    first = skills.propose('owner', a['id'], task['id'], **values)
    _, b, _ = store.create_message_and_task('owner', task['conversation_id'], 'Repeat successful test')
    store.finish_task(b['id'], status='completed')
    second = skills.propose('owner', a['id'], b['id'], **values)
    assert second['id'] != first['id']
    assert skills.list('owner', a['id'])[0]['source_task_id'] == b['id']
    _, c, _ = store.create_message_and_task('owner', task['conversation_id'], 'Revise')
    skills.propose('owner', a['id'], c['id'], **{**values, 'instructions': 'Read improved status'})
    skills.change('owner', a['id'], second['id'], enabled=False)
    store.finish_task(c['id'], status='completed')
    skills.finalize_task(c['id'], succeeded=True)
    assert not skills.list('owner', a['id'])[0]['enabled']
    assert skills.list('owner', a['id'], enabled_only=True) == []

