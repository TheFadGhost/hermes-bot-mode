"""Persistent leases for a small private desktop pool.

Lock order is allocation -> desktop. Actions/control/heartbeats take only a
desktop lock. Idle allocation skips busy desktops; explicit Pause waits
for the current action to finish. Time is wall time because lease deadlines survive process restart.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import inspect as pyinspect
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import HTTPException


class DesktopPool:
    def __init__(self, path: Path, driver: Any, *, capacity: int = 1,
                 idle_ttl: float = 300, viewer_ttl: float = 45,
                 task_ttl: float = 90, clock: Callable[[], float] = time.time):
        self.path, self.driver, self.clock = path, driver, clock
        self.capacity = max(1, capacity)
        self.idle_ttl, self.viewer_ttl, self.task_ttl = idle_ttl, viewer_ttl, task_ttl
        self.allocation = asyncio.Lock()
        self.locks: dict[str, asyncio.Lock] = {}
        self.records: dict[str, dict] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                self.records = loaded if isinstance(loaded, dict) else {}
            except (ValueError, OSError):
                # Containers are always enumerated independently at startup.
                self.records = {}

    def lock(self, agent: str) -> asyncio.Lock:
        return self.locks.setdefault(agent, asyncio.Lock())

    def record(self, agent: str) -> dict:
        return self.records.setdefault(agent, {"generation": 0, "control_mode": "bot",
            "phase": "sleeping", "last_activity": self.clock(), "leases": {}})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as output:
            json.dump(self.records, output, separators=(",", ":"))
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, self.path)

    def expire(self, record: dict) -> None:
        now = self.clock()
        record["leases"] = {key: lease for key, lease in record["leases"].items() if lease["expires_at"] > now}
        if record["control_mode"] == "manual" and not any(key.startswith("viewer:") for key in record["leases"]):
            record["control_mode"] = "bot"
            record["generation"] += 1
            record["needs_quiesce"] = True

    async def expire_locked(self, agent: str, record: dict) -> None:
        self.expire(record)
        if record.get("needs_quiesce"):
            # Server-side input policy changes and client disconnection complete
            # before this lock admits any new bot action. Fail closed on errors.
            self.save()
            if (await self.driver.inspect(agent)).get("running"):
                await self.driver.quiesce(agent, record["control_mode"])
            record.pop("needs_quiesce", None)
            self.save()

    def renew(self, record: dict, kind: str, identity: str) -> None:
        record["leases"][f"{kind}:{identity}"] = {"expires_at": self.clock() + (self.task_ttl if kind == "task" else self.viewer_ttl),
            "generation": record["generation"], "kind": kind}
        record["last_activity"] = self.clock()

    @staticmethod
    def generation(record: dict, generation: int) -> None:
        if generation != record["generation"]:
            raise HTTPException(409, "Computer ownership changed. Reopen the computer before continuing.")

    async def status(self, agent: str) -> dict:
        # Read-only status must never wake or extend a lease.
        async with self.lock(agent):
            record = self.record(agent)
            await self.expire_locked(agent, record)
            actual = await self.driver.inspect(agent)
            if not actual.get("running") and record["phase"] not in {"waiting", "waking", "failed"}:
                record["phase"] = "sleeping"
            self.save()
            return {**actual, "generation": record["generation"], "control_mode": record["control_mode"],
                "phase": record["phase"], "idle_timeout_seconds": self.idle_ttl}

    async def reconcile(self) -> None:
        async with self.allocation:
            agents = set(self.records) | set(await self.driver.list())
            for agent in agents:
                async with self.lock(agent):
                    record = self.record(agent)
                    actual = await self.driver.inspect(agent)
                    if actual.get("created"):
                        await self.driver.no_restart(agent)
                    await self.expire_locked(agent, record)
                    record["generation"] += 1
                    record["phase"] = "running" if actual.get("running") else "sleeping"
                    if actual.get("running"):
                        record["needs_quiesce"] = True
                        await self.expire_locked(agent, record)
                    if not actual.get("running"):
                        record["leases"] = {}
                        record["control_mode"] = "bot"
            self.save()
        await self.reap()

    async def _sleep_locked(self, agent: str, record: dict) -> None:
        record["phase"] = "sleeping"
        record["generation"] += 1
        record["leases"] = {}
        record["control_mode"] = "bot"
        self.save()
        try:
            await self.driver.stop(agent)
        except BaseException:
            record["phase"] = "failed"
            self.save()
            raise

    async def _reap_locked(self) -> None:
        for agent in list(self.records):
            lock = self.lock(agent)
            if lock.locked():
                continue
            async with lock:
                record = self.record(agent)
                await self.expire_locked(agent, record)
                if record["leases"] or self.clock() - record["last_activity"] < self.idle_ttl:
                    continue
                if (await self.driver.inspect(agent)).get("running"):
                    await self._sleep_locked(agent, record)
        self.save()

    async def reap(self) -> None:
        async with self.allocation:
            await self._reap_locked()

    @asynccontextmanager
    async def waiting_allocation(self, deadline: float, cancelled):
        while True:
            if cancelled:
                result = cancelled()
                if pyinspect.isawaitable(result):
                    result = await result
                if result:
                    raise HTTPException(409, "Computer request was cancelled")
            if self.allocation.locked() and time.monotonic() >= deadline:
                raise HTTPException(409, "Waiting for a free computer timed out")
            try:
                await asyncio.wait_for(self.allocation.acquire(), timeout=0.25)
                break
            except asyncio.TimeoutError:
                continue
        try:
            yield
        finally:
            self.allocation.release()

    async def wake(self, agent: str, *, task_id: str | None = None,
                   viewer_id: str | None = None, wait_timeout: float = 60,
                   cancelled: Callable | None = None) -> dict:
        deadline = time.monotonic() + max(0, min(wait_timeout, 120))
        try:
            while True:
                if cancelled:
                    result = cancelled()
                    if pyinspect.isawaitable(result):
                        result = await result
                    if result:
                        raise HTTPException(409, "Computer request was cancelled")
                async with self.waiting_allocation(deadline, cancelled):
                    await self._reap_locked()
                    lock = self.lock(agent)
                    if not lock.locked():
                        async with lock:
                            record = self.record(agent)
                            await self.expire_locked(agent, record)
                            if task_id and record["control_mode"] == "manual":
                                raise HTTPException(409, "You are controlling this computer. Return control to the bot first.")
                            actual = await self.driver.inspect(agent)
                            running = await self.driver.running()
                            if actual.get("running") or len(running) < self.capacity:
                                if not actual.get("running"):
                                    record["phase"] = "waking"
                                    record["generation"] += 1
                                    record["leases"] = {}
                                    self.save()
                                    try:
                                        actual = await self.driver.start(agent)
                                        await self.driver.quiesce(agent, "bot")
                                    except BaseException:
                                        record["phase"] = "failed"
                                        record["last_activity"] = self.clock() - self.idle_ttl
                                        self.save()
                                        raise
                                record["phase"] = "running"
                                self.renew(record, "task" if task_id else "viewer", task_id or viewer_id or "open")
                                self.save()
                                return {**actual, "phase": "running", "generation": record["generation"], "control_mode": record["control_mode"]}
                            record["phase"] = "waiting"
                            self.save()
                if time.monotonic() >= deadline:
                    raise HTTPException(409, "Waiting for a free computer timed out. The other computer is still in use.")
                await asyncio.sleep(min(0.25, max(0, deadline - time.monotonic())))
        except BaseException:
            # Do not turn a bounded capacity timeout into an unbounded wait on
            # an existing action. This synchronous update cannot interleave.
            record = self.record(agent)
            if record["phase"] == "waiting" and not self.lock(agent).locked():
                record["phase"] = "sleeping"
                self.save()
            raise

    async def stop(self, agent: str) -> dict:
        async with self.allocation:
            # Explicit owner Pause waits for a currently executing action to
            # quiesce; automatic idle reassignment never waits/evicts it.
            async with self.lock(agent):
                record = self.record(agent)
                await self._sleep_locked(agent, record)
                return {**await self.driver.inspect(agent), "phase": "sleeping", "control_mode": "bot", "generation": record["generation"]}

    async def control(self, agent: str, mode: str, viewer_id: str) -> dict:
        if mode not in {"manual", "bot"}:
            raise HTTPException(422, "Control mode must be manual or bot")
        async with self.lock(agent):
            record = self.record(agent)
            await self.expire_locked(agent, record)
            if not (await self.driver.inspect(agent)).get("running"):
                raise HTTPException(409, "Open the computer first")
            if record["control_mode"] != mode:
                record["generation"] += 1
                record["control_mode"] = mode
                record["needs_quiesce"] = True
                # Takeover revokes every old task token; callers must explicitly
                # acquire a new lease after control is returned.
                record["leases"] = {key: value for key, value in record["leases"].items() if key.startswith("viewer:")}
            self.renew(record, "viewer", viewer_id)
            await self.expire_locked(agent, record)
            self.save()
            return {**await self.driver.inspect(agent), "phase": "running", "control_mode": mode, "generation": record["generation"]}

    async def heartbeat(self, agent: str, generation: int, visible: bool, viewer_id: str) -> dict:
        async with self.lock(agent):
            record = self.record(agent)
            await self.expire_locked(agent, record)
            self.generation(record, generation)
            if visible:
                if not (await self.driver.inspect(agent)).get("running"):
                    raise HTTPException(409, "The computer is sleeping")
                self.renew(record, "viewer", viewer_id)
            else:
                record["leases"].pop(f"viewer:{viewer_id}", None)
                await self.expire_locked(agent, record)
            self.save()
            return {"generation": record["generation"], "control_mode": record["control_mode"], "phase": record["phase"]}

    async def heartbeat_task(self, agent: str, task_id: str, generation: int) -> dict:
        async with self.lock(agent):
            record = self.record(agent)
            await self.expire_locked(agent, record)
            self.generation(record, generation)
            lease = record["leases"].get(f"task:{task_id}")
            if record["control_mode"] != "bot" or not lease or lease["generation"] != generation:
                raise HTTPException(409, "Computer task lease expired")
            if not (await self.driver.inspect(agent)).get("running"):
                raise HTTPException(409, "The computer is sleeping")
            self.renew(record, "task", task_id)
            self.save()
            return {"generation": generation, "renewed": True}

    async def release_task(self, agent: str, task_id: str) -> None:
        async with self.lock(agent):
            self.record(agent)["leases"].pop(f"task:{task_id}", None)
            self.save()

    async def action(self, agent: str, params: dict, *, generation: int, task_id: str, cancelled=None) -> dict:
        async with self.lock(agent):
            if cancelled:
                result = cancelled()
                if pyinspect.isawaitable(result):
                    result = await result
                if result:
                    raise HTTPException(409, "Computer action was cancelled")
            record = self.record(agent)
            await self.expire_locked(agent, record)
            self.generation(record, generation)
            if record["control_mode"] != "bot":
                raise HTTPException(409, "Bot actions are paused while you control this computer")
            lease = record["leases"].get(f"task:{task_id}")
            if not lease or lease["generation"] != generation:
                raise HTTPException(409, "Computer task lease expired. Start the computer again.")
            if not (await self.driver.inspect(agent)).get("running"):
                raise HTTPException(409, "The computer is sleeping")
            self.renew(record, "task", task_id)
            self.save()
            operation = asyncio.create_task(self.driver.action(agent, params))
            try:
                return {**await asyncio.shield(operation), "generation": generation}
            except asyncio.CancelledError:
                # Killing a docker CLI does not kill the in-container exec.
                # Keep ownership until the bounded operation really finishes.
                await asyncio.shield(asyncio.gather(operation, return_exceptions=True))
                raise
            finally:
                # Lock excludes idle stop and manual takeover throughout the
                # action and screenshot, including error cleanup.
                self.renew(record, "task", task_id)
                self.save()

