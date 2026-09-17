"""Desktop lifecycle contracts with no Docker or production dependencies."""
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from desktop.lifecycle import DesktopPool


class Driver:
    def __init__(self):
        self.live = set()
        self.created = set()
        self.events = []
        self.entered = asyncio.Event()
        self.finish = None

    async def inspect(self, agent):
        return {'created': agent in self.created, 'running': agent in self.live, 'port': 1234}

    async def list(self):
        return list(self.created)

    async def running(self):
        return list(self.live)

    async def no_restart(self, agent):
        self.events.append(('restart_no', agent))

    async def start(self, agent):
        self.created.add(agent)
        self.live.add(agent)
        self.events.append(('start', agent))
        return await self.inspect(agent)

    async def stop(self, agent):
        self.events.append(('stop', agent))
        self.live.discard(agent)

    async def quiesce(self, agent, mode):
        self.events.append(('quiesce', agent, mode))

    async def action(self, agent, params):
        self.entered.set()
        if self.finish:
            await self.finish.wait()
        self.events.append(('action', agent))
        return {'ok': True}


@pytest.fixture
def env(tmp_path):
    now = [1000.0]
    driver = Driver()
    pool = DesktopPool(tmp_path / 'leases.json', driver, clock=lambda: now[0])
    return pool, driver, now


@pytest.mark.asyncio
async def test_idle_stops_but_preserves_profile_container(env):
    pool, driver, now = env
    await pool.wake('a', task_id='task')
    now[0] += 301
    await pool.reap()
    assert driver.live == set()
    assert driver.created == {'a'}
    assert (await pool.status('a'))['phase'] == 'sleeping'


@pytest.mark.asyncio
async def test_visible_viewer_protects_capacity_without_eviction(env):
    pool, driver, now = env
    state = await pool.wake('a', viewer_id='session')
    for _ in range(20):
        now[0] += 20
        await pool.heartbeat('a', state['generation'], True, 'session')
        await pool.reap()
    with pytest.raises(HTTPException) as exc:
        await pool.wake('b', task_id='other', wait_timeout=0)
    assert exc.value.status_code == 409
    assert driver.live == {'a'}
    assert pool.record('b')['phase'] == 'sleeping'


@pytest.mark.asyncio
async def test_hidden_viewer_does_not_renew_and_manual_expires(env):
    pool, driver, now = env
    await pool.wake('a', viewer_id='session')
    manual = await pool.control('a', 'manual', 'session')
    hidden = await pool.heartbeat('a', manual['generation'], False, 'session')
    assert hidden['control_mode'] == 'bot'
    assert hidden['generation'] > manual['generation']
    assert driver.events[-1] == ('quiesce', 'a', 'bot')
    now[0] += 301
    await pool.reap()
    assert not driver.live


@pytest.mark.asyncio
async def test_manual_rejects_actions_and_old_generation_after_return(env):
    pool, driver, now = env
    start = await pool.wake('a', task_id='task')
    await pool.control('a', 'manual', 'session')
    with pytest.raises(HTTPException):
        await pool.action('a', {}, generation=start['generation'], task_id='task')
    with pytest.raises(HTTPException):
        await pool.wake('a', task_id='task')
    await pool.control('a', 'bot', 'session')
    with pytest.raises(HTTPException):
        await pool.action('a', {}, generation=start['generation'], task_id='task')
    fresh = await pool.wake('a', task_id='task')
    assert (await pool.action('a', {}, generation=fresh['generation'], task_id='task'))['ok']


@pytest.mark.asyncio
async def test_takeover_and_idle_wait_for_active_action(env):
    pool, driver, now = env
    start = await pool.wake('a', task_id='task')
    driver.finish = asyncio.Event()
    action = asyncio.create_task(pool.action('a', {}, generation=start['generation'], task_id='task'))
    await driver.entered.wait()
    now[0] += 1000
    await pool.reap()
    assert driver.live == {'a'}
    takeover = asyncio.create_task(pool.control('a', 'manual', 'session'))
    await asyncio.sleep(0)
    assert not takeover.done()
    driver.finish.set()
    await action
    await takeover
    assert driver.events.index(('action', 'a')) < driver.events.index(('quiesce', 'a', 'manual'))


@pytest.mark.asyncio
async def test_cancelled_action_holds_lock_until_exec_finishes(env):
    pool, driver, now = env
    start = await pool.wake('a', task_id='task')
    driver.finish = asyncio.Event()
    action = asyncio.create_task(pool.action('a', {}, generation=start['generation'], task_id='task'))
    await driver.entered.wait()
    action.cancel()
    takeover = asyncio.create_task(pool.control('a', 'manual', 'session'))
    await asyncio.sleep(0)
    assert not takeover.done()
    driver.finish.set()
    with pytest.raises(asyncio.CancelledError):
        await action
    await takeover


@pytest.mark.asyncio
async def test_cancelled_capacity_wait_does_not_wake(env):
    pool, driver, now = env
    await pool.wake('a', task_id='task')
    cancel = [False]
    waiting = asyncio.create_task(pool.wake('b', task_id='other', cancelled=lambda: cancel[0]))
    await asyncio.sleep(0.01)
    cancel[0] = True
    with pytest.raises(HTTPException) as exc:
        await asyncio.wait_for(waiting, 1)
    assert 'cancelled' in exc.value.detail
    assert driver.live == {'a'}


@pytest.mark.asyncio
async def test_allocation_lock_wait_is_bounded(env):
    pool, driver, now = env
    await pool.allocation.acquire()
    try:
        with pytest.raises(HTTPException):
            await asyncio.wait_for(pool.wake('a', task_id='task', wait_timeout=0), 1)
    finally:
        pool.allocation.release()
    assert not driver.live


@pytest.mark.asyncio
async def test_restart_finds_unrecorded_containers_and_disables_restart(env):
    pool, driver, now = env
    driver.live.add('legacy')
    driver.created.add('legacy')
    await pool.reconcile()
    assert ('restart_no', 'legacy') in driver.events
    assert ('quiesce', 'legacy', 'bot') in driver.events
    assert pool.record('legacy')['phase'] == 'running'
    now[0] += 301
    await pool.reap()
    assert not driver.live


@pytest.mark.asyncio
async def test_restart_preserves_visible_manual_lease_but_revokes_old_generation(env):
    pool, driver, now = env
    await pool.wake('a', viewer_id='session')
    manual = await pool.control('a', 'manual', 'session')
    restarted = DesktopPool(pool.path, driver, clock=lambda: now[0])
    await restarted.reconcile()
    state = await restarted.status('a')
    assert state['control_mode'] == 'manual'
    assert state['generation'] > manual['generation']
    assert driver.live == {'a'}


@pytest.mark.asyncio
async def test_readonly_status_does_not_keep_desktop_alive(env):
    pool, driver, now = env
    await pool.wake('a', viewer_id='session')
    for _ in range(31):
        now[0] += 10
        await pool.status('a')
    await pool.reap()
    assert not driver.live


@pytest.mark.asyncio
async def test_expired_task_cannot_reuse_current_generation(env):
    pool, driver, now = env
    start = await pool.wake('a', task_id='task')
    now[0] += 91
    with pytest.raises(HTTPException) as exc:
        await pool.action('a', {}, generation=start['generation'], task_id='task')
    assert 'lease expired' in exc.value.detail


@pytest.mark.asyncio
async def test_released_task_cannot_act(env):
    pool, driver, now = env
    start = await pool.wake('a', task_id='task')
    await pool.release_task('a', 'task')
    with pytest.raises(HTTPException):
        await pool.action('a', {}, generation=start['generation'], task_id='task')


@pytest.mark.asyncio
async def test_expired_idle_slot_reassigned(env):
    pool, driver, now = env
    await pool.wake('a', task_id='task')
    now[0] += 301
    await pool.wake('b', task_id='other', wait_timeout=0)
    assert driver.live == {'b'}
    assert driver.events.index(('stop', 'a')) < driver.events.index(('start', 'b'))

@pytest.mark.asyncio
async def test_active_task_heartbeat_protects_idle_slot(env):
    pool, driver, now = env
    start = await pool.wake('a', task_id='task')
    for _ in range(15):
        now[0] += 30
        await pool.heartbeat_task('a', 'task', start['generation'])
        await pool.reap()
    assert driver.live == {'a'}
    await pool.release_task('a', 'task')
    now[0] += 301
    await pool.reap()
    assert not driver.live


@pytest.mark.asyncio
async def test_queued_cancelled_action_does_not_execute(env):
    pool, driver, now = env
    start = await pool.wake('a', task_id='task')
    await pool.lock('a').acquire()
    action = asyncio.create_task(pool.action('a', {}, generation=start['generation'], task_id='task', cancelled=lambda: True))
    await asyncio.sleep(0)
    pool.lock('a').release()
    with pytest.raises(HTTPException):
        await action
    assert ('action', 'a') not in driver.events


@pytest.mark.asyncio
async def test_failed_vnc_handoff_fails_closed(env):
    pool, driver, now = env
    await pool.wake('a', task_id='task')
    await pool.control('a', 'manual', 'session')
    async def broken(*args):
        raise HTTPException(503, 'VNC unavailable')
    driver.quiesce = broken
    with pytest.raises(HTTPException):
        await pool.control('a', 'bot', 'session')
    with pytest.raises(HTTPException):
        await pool.wake('a', task_id='next')
    assert ('action', 'a') not in driver.events

