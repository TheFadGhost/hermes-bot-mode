"""Private procedural references, promoted only after their source task succeeds.

These are recallable data, never system/developer instructions. Revisions keep
their evidence and provenance; an unsuccessful attempt cannot replace a working
procedure. A bot cannot modify another bot's procedures.
"""
from __future__ import annotations

import re
import time
import uuid
from typing import Any

from .errors import APIError
from .store import Store


class LearnedSkills:
    def __init__(self, store: Store):
        self.store = store
        with store.db.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS learned_skills (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                name TEXT NOT NULL, trigger TEXT NOT NULL, instructions TEXT NOT NULL,
                evidence TEXT NOT NULL, source_task_id TEXT NOT NULL REFERENCES tasks(id),
                revision INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                state TEXT NOT NULL DEFAULT 'pending', updated_at INTEGER NOT NULL,
                UNIQUE(user_id, agent_id, name, revision))""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_learned_skills_owner ON learned_skills(user_id,agent_id,state)")

    def propose(self, user_id: str, agent_id: str, task_id: str, *, name: str,
                trigger: str, instructions: str, evidence: str) -> dict[str, Any]:
        self.store.get_agent(user_id, agent_id)
        task = self.store.get_task(user_id, task_id)
        if task['agent_id'] != agent_id:
            raise APIError(403, 'skill_scope', 'A procedure must belong to its source bot')
        if task['status'] not in {'running', 'queued', 'completed'}:
            raise APIError(409, 'skill_task_failed', 'Only successful work can become a procedure')
        name = re.sub(r'\s+', ' ', name.strip()).casefold()
        values = {'name': name, 'trigger': trigger.strip(), 'instructions': instructions.strip(), 'evidence': evidence.strip()}
        for key, maximum in [('name', 100), ('trigger', 500), ('instructions', 12000), ('evidence', 2000)]:
            if not values[key] or len(values[key]) > maximum:
                raise APIError(422, 'skill_invalid', f'{key} is required and limited to {maximum} characters')
        with self.store.db.transaction(immediate=True) as db:
            latest = db.execute('SELECT * FROM learned_skills WHERE user_id=? AND agent_id=? AND name=? ORDER BY revision DESC LIMIT 1',
                                (user_id, agent_id, name)).fetchone()
            if latest and all(latest[k] == values[k] for k in ('trigger', 'instructions')) and (latest['state'] == 'ready' or (latest['state'] == 'pending' and latest['source_task_id'] == task_id)):
                return dict(latest)
            skill_id = uuid.uuid4().hex
            revision = latest['revision'] + 1 if latest else 1
            db.execute('INSERT INTO learned_skills(id,user_id,agent_id,name,trigger,instructions,evidence,source_task_id,revision,updated_at,enabled) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (skill_id, user_id, agent_id, name, values['trigger'], values['instructions'], values['evidence'], task_id, revision, int(time.time()), latest['enabled'] if latest else 1))
        if task['status'] == 'completed':
            self.finalize_task(task_id, succeeded=True)
        return {'id': skill_id, 'name': name, 'revision': revision, 'state': 'ready' if task['status'] == 'completed' else 'pending'}

    def finalize_task(self, task_id: str, *, succeeded: bool) -> None:
        with self.store.db.transaction(immediate=True) as db:
            task = db.execute('SELECT status FROM tasks WHERE id=?', (task_id,)).fetchone()
            ready = succeeded and task and task['status'] == 'completed'
            pending = db.execute("SELECT * FROM learned_skills WHERE source_task_id=? AND state='pending'", (task_id,)).fetchall()
            for row in pending:
                if ready:
                    db.execute("UPDATE learned_skills SET state='superseded' WHERE user_id=? AND agent_id=? AND name=? AND state='ready' AND revision<?",
                               (row['user_id'], row['agent_id'], row['name'], row['revision']))
                    newer = db.execute("SELECT 1 FROM learned_skills WHERE user_id=? AND agent_id=? AND name=? AND state='ready' AND revision>?",
                                       (row['user_id'], row['agent_id'], row['name'], row['revision'])).fetchone()
                    state = 'superseded' if newer else 'ready'
                else:
                    state = 'discarded'
                db.execute('UPDATE learned_skills SET state=? WHERE id=?', (state, row['id']))

    def list(self, user_id: str, agent_id: str, *, query: str = '', enabled_only: bool = False) -> list[dict[str, Any]]:
        self.store.get_agent(user_id, agent_id)
        clauses = ["user_id=?", "agent_id=?", "state='ready'"]
        params: list[Any] = [user_id, agent_id]
        if enabled_only:
            clauses.append('enabled=1')
        terms = set(re.findall(r'\w{3,}', query[:1000].casefold()))
        if query and not terms:
            return []
        with self.store.db.read() as db:
            # Evaluate matching before LIMIT without loading an unbounded collection
            # of instructions into Python. Token matching preserves Unicode casefold
            # and word boundaries used by earlier procedure search.
            if terms:
                db.create_function('procedure_matches', 2,
                    lambda name, trigger: len(terms.intersection(re.findall(r'\w{3,}', (name + ' ' + trigger).casefold()))))
                clauses.append('procedure_matches(name,trigger)>0')
            rank = 'procedure_matches(name,trigger) DESC,' if terms else ''
            rows = [dict(row) for row in db.execute(
                f"SELECT * FROM learned_skills WHERE {' AND '.join(clauses)} ORDER BY {rank}updated_at DESC,revision DESC,id DESC LIMIT ?",
                (*params, 8 if enabled_only else 200))]
        for row in rows:
            row['enabled'] = bool(row['enabled'])
        return rows

    def change(self, user_id: str, agent_id: str, skill_id: str, *, enabled: bool | None = None, delete: bool = False) -> None:
        self.store.get_agent(user_id, agent_id)
        with self.store.db.transaction() as db:
            row = db.execute("SELECT name FROM learned_skills WHERE id=? AND user_id=? AND agent_id=? AND state='ready'", (skill_id, user_id, agent_id)).fetchone()
            if not row:
                raise APIError(404, 'skill_missing', 'Procedure not found')
            if delete:
                db.execute('DELETE FROM learned_skills WHERE user_id=? AND agent_id=? AND name=?', (user_id, agent_id, row['name']))
            else:
                db.execute('UPDATE learned_skills SET enabled=? WHERE user_id=? AND agent_id=? AND name=?', (int(bool(enabled)), user_id, agent_id, row['name']))

