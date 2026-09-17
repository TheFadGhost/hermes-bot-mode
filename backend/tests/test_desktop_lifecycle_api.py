from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.desktop_api import register_desktop_routes
from app.desktops import DesktopManager


def test_control_and_heartbeat_enforce_owner_origin_and_identity():
    api = FastAPI()
    desktop = SimpleNamespace(control=AsyncMock(return_value={'generation': 2}), heartbeat=AsyncMock(return_value={'generation': 2}))
    def agent(owner, agent_id):
        if owner != 'owner' or agent_id != 'mine':
            raise HTTPException(404)
    store = SimpleNamespace(get_agent=agent)
    def session():
        return SimpleNamespace(user_id='owner', id='server-session')
    def origin(request: Request):
        if request.headers.get('origin') != 'http://testserver':
            raise HTTPException(403)
    register_desktop_routes(api, store=store, desktop=desktop, current_session=session, require_origin=origin)
    with TestClient(api) as client:
        headers = {'origin': 'http://testserver'}
        assert client.post('/agents/mine/desktop/control', json={'mode': 'manual'}, headers=headers).status_code == 200
        desktop.control.assert_awaited_once_with('mine', 'manual', viewer_id='server-session')
        assert client.post('/agents/mine/desktop/heartbeat', json={'generation': 2, 'visible': False}, headers=headers).status_code == 200
        desktop.heartbeat.assert_awaited_once_with('mine', 2, False, viewer_id='server-session')
        assert client.post('/agents/other/desktop/control', json={'mode': 'manual'}, headers=headers).status_code == 404
        assert client.post('/agents/mine/desktop/control', json={'mode': 'manual'}).status_code == 403
        assert client.post('/agents/mine/desktop/control', json={'mode': 'invalid'}, headers=headers).status_code == 422


@pytest.mark.asyncio
async def test_action_identity_overrides_model_arguments():
    manager = DesktopManager(secret='test')
    manager._task_generations[('a', 'trusted')] = 7
    manager._request = AsyncMock(return_value={'ok': True})
    await manager.action('a', {'action': 'screenshot', 'task_id': 'forged', 'generation': 123}, task_id='trusted')
    manager._request.assert_awaited_once_with('POST', '/desktops/a/action', {'action': 'screenshot', 'task_id': 'trusted', 'generation': 7})


def test_viewer_url_carries_generation_and_viewonly_policy():
    manager = DesktopManager()
    state = manager._public('a', {'running': True, 'generation': 7, 'control_mode': 'bot'})
    assert 'view_only=true' in state['view_url']
    assert 'websockify%3Fgeneration%3D7' in state['view_url']
    manual = manager._public('a', {'running': True, 'generation': 8, 'control_mode': 'manual'})
    assert 'view_only=false' in manual['view_url']

