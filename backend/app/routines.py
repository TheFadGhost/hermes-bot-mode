"""Durable wall-clock routines: one occurrence, one chat request, no overlap."""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import APIError


def next_due(after: int, clock: str, zone: str, weekdays: list[int]) -> int:
    """Choose the first fold; spring gaps run at the first valid later minute."""
    tz = ZoneInfo(zone)
    hour, minute = map(int, clock.split(":"))
    local = datetime.fromtimestamp(after,timezone.utc).astimezone(tz)
    for offset in range(9):
        date = local.date() + timedelta(days=offset)
        if date.weekday() not in weekdays:
            continue
        candidate = datetime(date.year,date.month,date.day,hour,minute,tzinfo=tz,fold=0)
        for _ in range(181):
            stamp = int(candidate.timestamp())
            roundtrip = datetime.fromtimestamp(stamp,timezone.utc).astimezone(tz)
            if roundtrip.replace(tzinfo=None) == candidate.replace(tzinfo=None):
                break
            candidate += timedelta(minutes=1)
        if stamp>after:
            return stamp
    raise ValueError("No scheduled day found")


def validate(values: dict[str,Any]) -> dict[str,Any]:
    values = dict(values)
    if not isinstance(values.get("name"),str) or not 1<=len(values["name"].strip())<=100:
        raise APIError(422,"routine_name","Give the routine a short name")
    if not isinstance(values.get("instruction"),str) or not 1<=len(values["instruction"].strip())<=12000:
        raise APIError(422,"routine_instruction","Describe what the bot should do")
    try:
        parts = values["time"].split(":")
        if len(parts)!=2 or len(values["time"])!=5 or not 0<=int(parts[0])<=23 or not 0<=int(parts[1])<=59:
            raise ValueError()
        ZoneInfo(values["timezone"])
    except (KeyError,TypeError,ValueError,ZoneInfoNotFoundError):
        raise APIError(422,"routine_time","Choose a valid time and timezone")
    days = values.get("weekdays")
    if not isinstance(days,list) or not days or any(type(day) is not int or not 0<=day<=6 for day in days):
        raise APIError(422,"routine_days","Choose at least one day of the week")
    values["weekdays"] = sorted(set(days))
    values["enabled"] = bool(values.get("enabled",True))
    return values


class Routines:
    def __init__(self, store: Any, messenger: Any, tasks: Any):
        self.store,self.messenger,self.tasks = store,messenger,tasks
        self.worker: asyncio.Task | None = None
        with store.db.transaction() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS routines(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,agent_id TEXT NOT NULL,
              name TEXT NOT NULL,instruction TEXT NOT NULL,time TEXT NOT NULL,timezone TEXT NOT NULL,weekdays_json TEXT NOT NULL,
              enabled INTEGER NOT NULL,archived INTEGER NOT NULL DEFAULT 0,next_due INTEGER NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
              created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS routine_occurrences(routine_id TEXT NOT NULL,occurrence TEXT NOT NULL,
              revision INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'claimed',request_id TEXT NOT NULL,task_id TEXT,
              claimed_at INTEGER NOT NULL,PRIMARY KEY(routine_id,occurrence));
            """)
            if "payload_json" not in {row["name"] for row in db.execute("PRAGMA table_info(routine_occurrences)")}:
                db.execute("ALTER TABLE routine_occurrences ADD COLUMN payload_json TEXT")

    @staticmethod
    def _row(row: Any) -> dict[str,Any]:
        item = dict(row)
        item["weekdays"] = json.loads(item.pop("weekdays_json"))
        item["enabled"] = bool(item["enabled"])
        return item

    def get(self,user: str,routine: str) -> dict[str,Any]:
        with self.store.db.read() as db:
            row = db.execute("SELECT * FROM routines WHERE id=? AND user_id=? AND archived=0",(routine,user)).fetchone()
        if not row:
            raise APIError(404,"routine_missing","This routine was not found")
        return self._row(row)

    def list(self,user: str,agent: str) -> list[dict[str,Any]]:
        self.store.get_agent(user,agent)
        with self.store.db.read() as db:
            return [self._row(row) for row in db.execute("SELECT * FROM routines WHERE user_id=? AND agent_id=? AND archived=0 ORDER BY created_at",(user,agent))]

    def save(self,user: str,agent: str,values: dict[str,Any],routine: str | None = None) -> dict[str,Any]:
        self.store.get_agent(user,agent)
        old = self.get(user,routine) if routine else {}
        values = validate({**old,**values})
        now = int(time.time())
        due = next_due(now,values["time"],values["timezone"],values["weekdays"])
        routine = routine or str(uuid.uuid4())
        with self.store.db.transaction(immediate=True) as db:
            db.execute("""INSERT INTO routines(id,user_id,agent_id,name,instruction,time,timezone,weekdays_json,enabled,next_due,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,instruction=excluded.instruction,
              time=excluded.time,timezone=excluded.timezone,weekdays_json=excluded.weekdays_json,enabled=excluded.enabled,
              next_due=excluded.next_due,revision=routines.revision+1,updated_at=excluded.updated_at""",
              (routine,user,agent,values["name"].strip(),values["instruction"].strip(),values["time"],values["timezone"],json.dumps(values["weekdays"]),int(values["enabled"]),due,now,now))
        return self.get(user,routine)

    def archive(self,user: str,routine: str) -> None:
        self.get(user,routine)
        with self.store.db.transaction(immediate=True) as db:
            db.execute("UPDATE routines SET archived=1,enabled=0,revision=revision+1 WHERE id=? AND user_id=?",(routine,user))

    def run(self,user: str,routine: str,*,client_request_id: str | None = None,occurrence: str | None = None) -> dict[str,Any]:
        item = self.get(user,routine)
        agent = self.store.get_agent(user,item["agent_id"])
        if agent["status"] != "active":
            raise APIError(409,"bot_paused","Resume the bot before running this routine")
        if client_request_id is not None and (not isinstance(client_request_id,str) or not client_request_id.strip()):
            raise APIError(422,"request_id_invalid","Use a nonempty request ID")
        occurrence = occurrence or "manual:" + (client_request_id or str(uuid.uuid4()))
        if len(occurrence)>180:
            raise APIError(422,"request_id_invalid","The request ID is too long")
        request_id = "routine:" + str(uuid.uuid5(uuid.NAMESPACE_URL,routine+":"+occurrence))
        home = self.messenger.home(user,item["agent_id"])
        payload = {"conversation_id":home["id"],"content":f"Routine: {item['name']}\n\n{item['instruction']}"}
        # Claim first, then use the same durable request ID after a crash. A
        # claim without a task is resumed by the scheduler, never duplicated.
        with self.store.db.transaction(immediate=True) as db:
            current = db.execute("SELECT enabled,archived,revision FROM routines WHERE id=?",(routine,)).fetchone()
            if current[1] or (occurrence.startswith("scheduled:") and (not current[0] or current[2]!=item["revision"])):
                raise APIError(409,"routine_changed","The routine changed before it could run")
            existing = db.execute("SELECT * FROM routine_occurrences WHERE routine_id=? AND occurrence=?",(routine,occurrence)).fetchone()
            if existing:
                if not existing["task_id"] and occurrence.startswith("scheduled:") and existing["revision"]!=current[2]:
                    raise APIError(409,"routine_changed","The routine changed after this occurrence was claimed")
                if existing["payload_json"]:
                    payload = json.loads(existing["payload_json"])
                elif not existing["task_id"]:
                    raise APIError(409,"routine_changed","This old occurrence has no saved instruction and was skipped")
            else:
                active = db.execute("SELECT 1 FROM routine_occurrences o LEFT JOIN tasks t ON t.id=o.task_id WHERE o.routine_id=? AND (o.task_id IS NULL OR t.status IN ('queued','running'))",(routine,)).fetchone()
                if active:
                    raise APIError(409,"routine_running","This routine is already working")
                db.execute("INSERT INTO routine_occurrences(routine_id,occurrence,revision,request_id,claimed_at,payload_json) VALUES(?,?,?,?,?,?)",(routine,occurrence,item["revision"],request_id,int(time.time()),json.dumps(payload)))
        # Synchronous operations do not yield between claim and creation; the
        # idempotency key also protects restart recovery and multiple workers.
        result = self.messenger.send(user,payload["conversation_id"],payload["content"],client_request_id=request_id)
        with self.store.db.transaction(immediate=True) as db:
            db.execute("UPDATE routine_occurrences SET task_id=?,status='submitted' WHERE routine_id=? AND occurrence=?",(result["task"]["id"],routine,occurrence))
        self.tasks.submit(user,result["task"]["id"])
        return {"task":result["task"],"request_id":result["request_id"]}

    async def tick(self) -> None:
        now = int(time.time())
        with self.store.db.read() as db:
            pending = db.execute("SELECT o.occurrence,r.* FROM routine_occurrences o JOIN routines r ON r.id=o.routine_id WHERE o.task_id IS NULL AND r.archived=0").fetchall()
            due = db.execute("SELECT * FROM routines WHERE enabled=1 AND archived=0 AND next_due<=?",(now,)).fetchall()
        for row in pending:
            try:
                self.run(row["user_id"],row["id"],occurrence=row["occurrence"])
            except APIError:
                with self.store.db.transaction() as db:
                    db.execute("UPDATE routine_occurrences SET status='skipped',task_id='' WHERE routine_id=? AND occurrence=?",(row["id"],row["occurrence"]))
        for row in due:
            item = self._row(row)
            # Only the latest missed occurrence is caught up after downtime.
            occurrence = "scheduled:"+str(item["next_due"])
            try:
                self.run(item["user_id"],item["id"],occurrence=occurrence)
            except APIError as exc:
                if exc.code != "routine_running":
                    self.store.activity(item["user_id"],"routine.error",{"routine_id":item["id"],"message":exc.message})
            with self.store.db.transaction() as db:
                db.execute("UPDATE routines SET next_due=? WHERE id=? AND revision=?",(next_due(now,item["time"],item["timezone"],item["weekdays"]),item["id"],item["revision"]))

    async def start(self) -> None:
        async def loop():
            while True:
                try:
                    await self.tick()
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception("Routine scheduler tick failed")
                await asyncio.sleep(15)
        self.worker = asyncio.create_task(loop(),name="bot-routines")

    async def close(self) -> None:
        if self.worker:
            self.worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.worker

