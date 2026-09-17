"""Bounded replacement and profile-safe desktop migration contracts."""
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from desktop import supervisor, vnc_server


def test_blocked_vnc_child_is_killed_before_replacement(monkeypatch):
    server = vnc_server.VNCServer()
    child = Mock()
    child.wait.side_effect = [subprocess.TimeoutExpired('x11vnc', 1), 0]
    server.child = child
    server.stop()
    assert child.method_calls == [('terminate', (), {}), ('wait', (), {'timeout': 1}),
                                  ('kill', (), {}), ('wait', (), {'timeout': 2})]
    assert server.child is None


@pytest.mark.parametrize('mode,viewonly', [('bot', True), ('manual', False)])
def test_replacement_applies_input_policy_at_startup(monkeypatch, mode, viewonly):
    server = vnc_server.VNCServer()
    old = Mock()
    server.child = old
    process = Mock(poll=Mock(return_value=None))
    def spawn(args):
        old.wait.assert_called_once_with(timeout=1)
        assert ('-viewonly' in args) == viewonly
        return process
    monkeypatch.setattr(vnc_server.subprocess, 'Popen', spawn)
    connection = Mock()
    connection.recv.return_value = b'RFB 003.008\n'
    context = Mock(__enter__=Mock(return_value=connection), __exit__=Mock(return_value=False))
    monkeypatch.setattr(vnc_server.socket, 'create_connection', lambda *args: context)
    server.change(mode)
    assert server.child is process


@pytest.mark.asyncio
async def test_old_running_desktop_never_recreated(monkeypatch):
    monkeypatch.setattr(supervisor, 'inspect', AsyncMock(return_value={'created': True, 'running': True}))
    commands = AsyncMock()
    monkeypatch.setattr(supervisor, 'command', commands)
    with pytest.raises(HTTPException) as error:
        await supervisor.docker_start('qa')
    assert error.value.status_code == 409
    commands.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_sleeping_container_replaced_with_same_profile(monkeypatch, tmp_path):
    profile = tmp_path / 'qa'
    profile.mkdir()
    marker = profile / 'History'
    marker.write_text('retained browser history')
    monkeypatch.setattr(supervisor, 'ROOT', tmp_path)
    monkeypatch.setattr(supervisor.os, 'chown', lambda *args: None, raising=False)
    monkeypatch.setattr(supervisor, 'inspect', AsyncMock(side_effect=[{'created': True, 'running': False}, {'created': True, 'running': True}]))
    commands = AsyncMock(return_value=b'[]')
    monkeypatch.setattr(supervisor, 'command', commands)
    await supervisor.docker_start('qa')
    calls = [call.args for call in commands.await_args_list]
    assert calls[0] == ('rm', 'dad-desktop-qa')
    run = next(call for call in calls if call[0] == 'run')
    assert 'dad-bot.desktop-version=2' in run
    assert f'type=bind,src={profile},dst=/profile' in run
    assert marker.read_text() == 'retained browser history'


@pytest.mark.asyncio
async def test_handoff_uses_independent_bounded_control_channel(monkeypatch):
    command = AsyncMock()
    monkeypatch.setattr(supervisor, 'command', command)
    await supervisor.DockerDriver().quiesce('qa', 'bot')
    command.assert_awaited_once_with('exec', 'dad-desktop-qa', 'timeout', '--kill-after=1', '16',
                                    'python3', '/usr/local/bin/desktop-vnc.py', 'bot', timeout=18)


def test_control_waits_for_startup_socket(monkeypatch):
    connection = Mock()
    connection.connect.side_effect = [FileNotFoundError(), ConnectionRefusedError(), None]
    connection.recv.side_effect = [b'{"ok":true}', b'']
    context = Mock(__enter__=Mock(return_value=connection), __exit__=Mock(return_value=False))
    monkeypatch.setattr(vnc_server.socket, 'AF_UNIX', 1, raising=False)
    monkeypatch.setattr(vnc_server.socket, 'socket', lambda *args: context)
    monkeypatch.setattr(vnc_server.time, 'sleep', lambda *args: None)
    vnc_server.control('bot', '/test/control.sock')
    assert connection.connect.call_count == 3
    connection.sendall.assert_called_once_with(b'bot')


def test_control_startup_wait_is_bounded(monkeypatch):
    connection = Mock()
    connection.connect.side_effect = FileNotFoundError()
    context = Mock(__enter__=Mock(return_value=connection), __exit__=Mock(return_value=False))
    monkeypatch.setattr(vnc_server.socket, 'AF_UNIX', 1, raising=False)
    monkeypatch.setattr(vnc_server.socket, 'socket', lambda *args: context)
    monkeypatch.setattr(vnc_server.time, 'monotonic', Mock(side_effect=[0, 1, 3]))
    monkeypatch.setattr(vnc_server.time, 'sleep', lambda *args: None)
    with pytest.raises(RuntimeError, match='Computer control is not ready'):
        vnc_server.control('bot')
    assert connection.connect.call_count == 2
    connection.sendall.assert_not_called()

