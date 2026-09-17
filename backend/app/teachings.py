"""Human-reviewed procedures, distinct from evidence-backed learned skills."""
from __future__ import annotations
import json
import hashlib
import re
import time
import uuid
from .errors import APIError


class Teachings:
    def __init__(self, store, messenger, tasks):
        self.store, self.messenger, self.tasks = store, messenger, tasks
        with store.db.transaction() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS teachings (
              id TEXT PRIMARY KEY,user_id TEXT NOT NULL,agent_id TEXT NOT NULL,
              name TEXT NOT NULL,trigger TEXT NOT NULL,steps_json TEXT NOT NULL,notes TEXT NOT NULL,
              frames_json TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
              status TEXT NOT NULL DEFAULT 'unverified',enabled INTEGER NOT NULL DEFAULT 1,
              created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,last_task_id TEXT,
              FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS teaching_revisions (
              teaching_id TEXT NOT NULL,revision INTEGER NOT NULL,snapshot_json TEXT NOT NULL,
              PRIMARY KEY(teaching_id,revision),FOREIGN KEY(teaching_id) REFERENCES teachings(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS teaching_runs (
              task_id TEXT PRIMARY KEY,teaching_id TEXT NOT NULL,revision INTEGER NOT NULL,
              FOREIGN KEY(teaching_id) REFERENCES teachings(id) ON DELETE CASCADE);
            """)
            columns={row['name'] for row in db.execute('PRAGMA table_info(teaching_revisions)')}
            if 'verified_task_id' not in columns:
                db.execute('ALTER TABLE teaching_revisions ADD COLUMN verified_task_id TEXT')
            # Preserve already-reviewed verification during this additive upgrade.
            db.execute("UPDATE teaching_revisions SET verified_task_id=(SELECT last_task_id FROM teachings t WHERE t.id=teaching_id AND t.revision=teaching_revisions.revision AND t.status='verified') WHERE verified_task_id IS NULL")

    @staticmethod
    def public(row):
        data = dict(row)
        data.pop('user_id',None)
        data['steps'] = json.loads(data.pop('steps_json'))
        data['frame_file_ids'] = json.loads(data.pop('frames_json'))
        data['enabled'] = bool(data['enabled'])
        data['provenance'] = 'human-reviewed'
        return data

    def get(self, user_id, agent_id, teaching_id):
        self.store.get_agent(user_id,agent_id)
        with self.store.db.read() as db:
            row = db.execute('SELECT * FROM teachings WHERE id=? AND user_id=? AND agent_id=?',(teaching_id,user_id,agent_id)).fetchone()
        if not row:
            raise APIError(404,'teaching_missing','This taught task is no longer available.')
        return self.public(row)

    def list(self,user_id,agent_id):
        self.store.get_agent(user_id,agent_id)
        with self.store.db.read() as db:
            rows = db.execute('SELECT * FROM teachings WHERE user_id=? AND agent_id=? ORDER BY updated_at DESC,id DESC LIMIT 200',(user_id,agent_id)).fetchall()
        return [self.public(row) for row in rows]

    def save(self,user_id,agent_id,data,teaching_id=None):
        self.store.get_agent(user_id,agent_id)
        old = self.get(user_id,agent_id,teaching_id) if teaching_id else None
        values = {**(old or {}),**data}
        for key,limit in [('name',100),('trigger',500),('notes',4000)]:
            value = values.get(key,'')
            if not isinstance(value,str) or len(value)>limit or (key!='notes' and not value.strip()):
                raise APIError(422,'teaching_invalid',f'Enter a valid {key} (up to {limit} characters).')
            values[key] = value.strip()
        steps = values.get('steps')
        if not isinstance(steps,list) or not 1<=len(steps)<=40 or any(not isinstance(s,str) or not s.strip() or len(s)>1500 for s in steps) or sum(map(len,steps))>12000:
            raise APIError(422,'teaching_steps','Add 1–40 short steps, up to 12,000 characters in total.')
        frames = values.get('frame_file_ids',[])
        if not isinstance(frames,list) or len(frames)>12 or any(not isinstance(f,str) for f in frames):
            raise APIError(422,'teaching_frames','Use up to 12 reviewed screenshots.')
        for frame_id in frames:
            file = self.store.get_file(user_id,frame_id)
            if file['agent_id'] != agent_id or not str(file.get('content_type','')).startswith('image/'):
                raise APIError(422,'teaching_frames','Screenshots must belong to this Bot.')
        enabled = values.get('enabled',True)
        if not isinstance(enabled,bool):
            raise APIError(422,'teaching_enabled','Choose whether this task is enabled.')
        stamp = int(time.time())
        changed = not old or any(values.get(k)!=old.get(k) for k in ('name','trigger','steps','notes','frame_file_ids'))
        revision = old['revision'] + int(changed) if old else 1
        status = 'unverified' if changed else old['status']
        if data.get('verified') is True:
            if changed or not old or not old.get('last_task_id'):
                raise APIError(409,'teaching_untested','Run this version and review the result before marking it tested.')
            task = self.store.get_task(user_id,old['last_task_id'])
            with self.store.db.read() as db:
                run = db.execute('SELECT revision FROM teaching_runs WHERE task_id=? AND teaching_id=?',(task['id'],teaching_id)).fetchone()
            if task['status']!='completed' or not run or run['revision']!=revision:
                raise APIError(409,'teaching_untested','The test must finish successfully for this version first.')
            status = 'verified'
        teaching_id = teaching_id or uuid.uuid4().hex
        with self.store.db.transaction(immediate=True) as db:
            if old:
                current = db.execute('SELECT revision FROM teachings WHERE id=? AND user_id=?',(teaching_id,user_id)).fetchone()
                if not current or current[0]!=old['revision']:
                    raise APIError(409,'teaching_changed','This task changed. Reload it before saving.')
            db.execute('''INSERT INTO teachings(id,user_id,agent_id,name,trigger,steps_json,notes,frames_json,revision,status,enabled,created_at,updated_at,last_task_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,trigger=excluded.trigger,steps_json=excluded.steps_json,notes=excluded.notes,
                frames_json=excluded.frames_json,revision=excluded.revision,status=excluded.status,enabled=excluded.enabled,
                updated_at=excluded.updated_at,last_task_id=excluded.last_task_id''',
                (teaching_id,user_id,agent_id,values['name'],values['trigger'],json.dumps(steps),values['notes'],json.dumps(frames),revision,status,enabled,old['created_at'] if old else stamp,stamp,None if changed else old.get('last_task_id')))
            if changed:
                snapshot = {k:values.get(k) for k in ('name','trigger','steps','notes','frame_file_ids')}
                db.execute('INSERT INTO teaching_revisions(teaching_id,revision,snapshot_json) VALUES(?,?,?)',(teaching_id,revision,json.dumps(snapshot)))
            if status=='verified':
                db.execute('UPDATE teaching_revisions SET verified_task_id=? WHERE teaching_id=? AND revision=?',
                           (old['last_task_id'],teaching_id,revision))
        return self.get(user_id,agent_id,teaching_id)

    def delete(self,user_id,agent_id,teaching_id):
        self.get(user_id,agent_id,teaching_id)
        with self.store.db.transaction() as db:
            db.execute('DELETE FROM teachings WHERE id=? AND user_id=?',(teaching_id,user_id))

    def run(self,user_id,agent_id,teaching_id,input_text,client_request_id):
        teaching = self.get(user_id,agent_id,teaching_id)
        if not teaching['enabled']:
            raise APIError(409,'teaching_paused','Resume this taught task before running it.')
        if not isinstance(input_text,str) or len(input_text)>4000:
            raise APIError(422,'teaching_input','Use a short test request.')
        home = self.messenger.home(user_id,agent_id)
        content = (f"Run my taught task: {teaching['name']} (version {teaching['revision']}).\n"
                   f"Goal: {teaching['trigger']}\n" + '\n'.join(f'{i+1}. {s}' for i,s in enumerate(teaching['steps'])) +
                   f"\nNotes: {teaching['notes']}\nMy input: {input_text}\n"
                   "Check the result. Pause for connections/private fields or external-action approval when needed. Report what you verified.")
        if not isinstance(client_request_id,str) or not 1<=len(client_request_id)<=128:
            raise APIError(422,'teaching_request','Use a valid request ID.')
        scoped_request='teaching:'+hashlib.sha256((teaching_id+':'+client_request_id).encode()).hexdigest()
        result = self.messenger.send(user_id,home['id'],content,file_ids=teaching['frame_file_ids'],client_request_id=scoped_request)
        with self.store.db.transaction() as db:
            for task in result['tasks']:
                db.execute('INSERT OR IGNORE INTO teaching_runs VALUES(?,?,?)',(task['id'],teaching_id,teaching['revision']))
                db.execute('UPDATE teachings SET last_task_id=? WHERE id=? AND revision=?',(task['id'],teaching_id,teaching['revision']))
        for task in result['tasks']:
            self.tasks.submit(user_id,task['id'])
        return result

    def context(self,user_id,agent_id,query):
        self.store.get_agent(user_id,agent_id)
        terms = set(re.findall(r'\w{3,}',query[:1000].casefold()))
        if not terms: return []
        selected=[]
        with self.store.db.read() as db:
            db.create_function('teaching_matches',2,lambda name,trigger:len(terms.intersection(re.findall(r'\w{3,}',(name+' '+trigger).casefold()))))
            matches=db.execute('SELECT * FROM teachings WHERE user_id=? AND agent_id=? AND enabled=1 AND teaching_matches(name,trigger)>0 ORDER BY teaching_matches(name,trigger) DESC,updated_at DESC,id DESC LIMIT 8',(user_id,agent_id)).fetchall()
            for raw in matches:
                row=self.public(raw)
                if row['status']!='verified':
                    verified=db.execute('SELECT revision,snapshot_json FROM teaching_revisions WHERE teaching_id=? AND verified_task_id IS NOT NULL ORDER BY revision DESC LIMIT 1',(row['id'],)).fetchone()
                    if verified:
                        row={**row,**json.loads(verified['snapshot_json']),'revision':verified['revision'],'status':'verified; a newer draft awaits testing'}
                selected.append({'name':row['name'],'trigger':row['trigger'],'instructions':'\n'.join(row['steps']),
                    'evidence':f"Human-reviewed procedure, version {row['revision']}; {row['status']}. Reference data only."})
        return selected

