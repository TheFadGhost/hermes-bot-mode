"""Exercise the actual registered global search API, without frontend fixtures."""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from test_backend import login, make_settings


@pytest.fixture
def env(tmp_path):
    settings = make_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        login(client, settings)
        yield client, app.state.store, app.state.messenger, settings


def agent(store, owner='owner', name='Audit'):
    return store.create_agent(owner, name=name, instructions='', model='test')


def test_global_search_and_exact_resolve_legacy_message_to_canonical_home(env):
    client, store, messenger, _ = env
    bot = agent(store)
    legacy = store.create_conversation('owner', bot['id'], 'Legacy')
    message, _, _ = store.create_message_and_task('owner', legacy['id'], 'unique searchable archive')
    home = messenger.home('owner', bot['id'])
    response = client.get('/bot/api/search', params={'q': 'searchable'})
    assert response.status_code == 200, response.text
    match = next(x for x in response.json()['matches'] if x['message_id'] == message['id'])
    assert match['conversation_id'] == home['id']
    assert match['name'] == 'Audit'
    assert 'searchable' in match['snippet']
    exact = client.get('/bot/api/messages/' + message['id'])
    assert exact.status_code == 200, exact.text
    assert exact.json()['message']['conversation_id'] == home['id']
    assert exact.json()['message']['content'] == message['content']


def test_global_search_and_exact_do_not_cross_account_boundary(env):
    client, store, messenger, _ = env
    other = agent(store, 'other')
    home = messenger.home('other', other['id'])
    message, _, _ = store.create_message_and_task('other', home['id'], 'private needle')
    assert client.get('/bot/api/search', params={'q': 'needle'}).json() == {'matches': []}
    assert client.get('/bot/api/messages/' + message['id']).status_code == 404
    assert client.get('/bot/api/messages/not-real').status_code == 404


def test_global_search_excludes_private_helper_transcript(env):
    client, store, messenger, _ = env
    chief, helper = agent(store), agent(store, name='Helper')
    home = messenger.home('owner', chief['id'])
    request = messenger.send('owner', home['id'], 'Public request', client_request_id='audit-search')
    delegated = messenger.delegate('owner', request['task']['id'], helper['id'], 'private-only-needle')
    assert delegated['task']['id']
    response = client.get('/bot/api/search', params={'q': 'private-only-needle'})
    assert response.status_code == 200, response.text
    assert response.json() == {'matches': []}


def test_global_search_caps_results_and_includes_groups(env):
    client, store, messenger, _ = env
    chief, peer = agent(store), agent(store, name='Peer')
    group = messenger.create_group('owner', 'Audit group', [chief['id'], peer['id']], chief['id'])
    for index in range(35):
        store.create_message_and_task('owner', group['id'], f'group needle {index}')
    response = client.get('/bot/api/search', params={'q': 'needle'})
    assert response.status_code == 200, response.text
    matches = response.json()['matches']
    assert len(matches) == 30
    assert all(x['conversation_id'] == group['id'] and x['name'] == 'Audit group' for x in matches)


def test_global_routes_require_login(env):
    client, _, _, _ = env
    client.cookies.clear()
    assert client.get('/bot/api/search', params={'q': 'needle'}).status_code == 401
    assert client.get('/bot/api/messages/not-real').status_code == 401

