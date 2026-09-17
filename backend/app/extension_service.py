"""Durable, scoped chat requests and approval-gated connector execution."""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import secrets
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse
from .errors import APIError
from .private_fields import PrivateFields, provider_key
from .teachings import Teachings


def text_arg(data,key,limit=500,required=True):
    value=data.get(key,'')
    if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):
        raise APIError(422,'field_invalid',f'Enter a valid {key.replace("_"," ")}.')
    return value.strip()


class Extensions:
    def __init__(self,store,messenger,tasks,settings):
        self.store,self.messenger,self.tasks,self.settings=store,messenger,tasks,settings
        self.private=PrivateFields(store,settings.database_path.parent/'private-vault.key')
        self.teachings=Teachings(store,messenger,tasks)
        self.connection_factory=None
        self._session_locks={}
        with store.db.transaction() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS connection_sessions(user_id TEXT PRIMARY KEY,session_id TEXT NOT NULL,key_hash TEXT NOT NULL,created_at INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS connection_tools(user_id TEXT NOT NULL,slug TEXT NOT NULL,schema_json TEXT NOT NULL,updated_at INTEGER NOT NULL,PRIMARY KEY(user_id,slug));
            CREATE TABLE IF NOT EXISTS connection_links(state_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,toolkit TEXT NOT NULL,expires_at INTEGER NOT NULL,consumed_at INTEGER);
            CREATE TABLE IF NOT EXISTS chat_requests(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,agent_id TEXT NOT NULL,conversation_id TEXT NOT NULL,
              task_id TEXT,kind TEXT NOT NULL,title TEXT NOT NULL,purpose TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
              data_json TEXT NOT NULL,result_json TEXT,error TEXT,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,
              FOREIGN KEY(agent_id) REFERENCES agents(id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS idx_chat_requests_owner ON chat_requests(user_id,conversation_id,created_at);
            ''')
            db.execute("UPDATE chat_requests SET status='uncertain',error='The service restarted during this action. Check the destination before doing it again.' WHERE status='executing'")
            db.execute("UPDATE private_fields SET state='quarantined' WHERE state='reserved'")
            columns={row['name'] for row in db.execute('PRAGMA table_info(connection_links)')}
            if 'account_id' not in columns: db.execute('ALTER TABLE connection_links ADD COLUMN account_id TEXT')
            if 'baseline_json' not in columns: db.execute("ALTER TABLE connection_links ADD COLUMN baseline_json TEXT NOT NULL DEFAULT '[]'")

    def provider(self,*,expected_binding=None,user_id=None):
        from .connection_provider import ConnectionProvider
        key=provider_key(self.settings,'COMPOSIO_API_KEY')
        if not key:
            raise APIError(503,'connections_unconfigured','Connections need the administrator’s Composio key first.')
        if expected_binding is not None and self._fingerprint([self.provider_user(user_id),key])!=expected_binding:
            raise APIError(409,'provider_changed','The connection configuration changed. Review a new action.')
        return (self.connection_factory or ConnectionProvider)(key)

    async def provider_call(self,method,*args):
        provider=self.provider()
        try:
            return await getattr(provider,method)(*args)
        finally:
            if hasattr(provider,'aclose'): await provider.aclose()

    def status(self):
        import os
        return {'connections':{'configured':bool(provider_key(self.settings,'COMPOSIO_API_KEY'))},
                'voice':{'configured':bool(provider_key(self.settings,'OPENROUTER_API_KEY')),'model':'microsoft/mai-transcribe-2','max_bytes':10485760,'max_seconds':120},
                'private_input':{'available':self.private.available},
                'telegram':{'configured':bool(os.getenv('BOT_TELEGRAM_BRIDGE_OWNER_ID') and os.getenv('BOT_TELEGRAM_BRIDGE_SECRET'))}}

    def provider_user(self,user_id):
        # Stable per installation, not an email or client-controlled identity.
        return 'hermes_'+hashlib.sha256((self.settings.session_secret+':'+user_id).encode()).hexdigest()[:32]

    async def session(self,user_id):
        key=provider_key(self.settings,'COMPOSIO_API_KEY')
        if not key:
            raise APIError(503,'connections_unconfigured','Connections need the administrator’s Composio key first.')
        fingerprint=hashlib.sha256(key.encode()).hexdigest()
        async with self._session_locks.setdefault(user_id,asyncio.Lock()):
            with self.store.db.read() as db:
                row=db.execute('SELECT * FROM connection_sessions WHERE user_id=?',(user_id,)).fetchone()
            if row and row['key_hash']==fingerprint and row['created_at']>time.time()-3600:
                return row['session_id']
            result=await self.provider_call('create_session',self.provider_user(user_id))
            session_id=result['session_id'] if isinstance(result,dict) else result
            if not isinstance(session_id,str) or not session_id:
                raise APIError(502,'connection_session','The connection service could not start a session.')
            with self.store.db.transaction() as db:
                db.execute('INSERT INTO connection_sessions VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET session_id=excluded.session_id,key_hash=excluded.key_hash,created_at=excluded.created_at',
                           (user_id,session_id,fingerprint,int(time.time())))
            return session_id

    async def connections(self,user_id,query='',cursor=''):
        if not self.status()['connections']['configured']:
            return {'configured':False,'catalog':[],'accounts':[],'next_cursor':None}
        session_id=await self.session(user_id)
        catalogue,accounts=await asyncio.gather(self.provider_call('catalog',session_id,query,cursor),self.provider_call('accounts',self.provider_user(user_id)))
        if isinstance(accounts,dict): accounts=accounts.get('accounts',[])
        if isinstance(catalogue,list): catalogue={'catalog':catalogue,'next_cursor':None}
        active={a['toolkit'] for a in accounts if str(a.get('status','')).upper()=='ACTIVE'}
        return {'configured':True,'catalog':[{**item,'connected':item.get('slug') in active} for item in catalogue.get('catalog',[])],
                'accounts':accounts,'next_cursor':catalogue.get('next_cursor')}

    async def link(self,user_id,toolkit):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',toolkit):
            raise APIError(422,'toolkit_invalid','Choose a service from Connections.')
        token=secrets.token_urlsafe(32)
        base=(self.settings.public_base_url or 'http://localhost:5173').rstrip('/')
        callback=base+'/bot/api/connections/callback?state='+token
        before=await self.provider_call('accounts',self.provider_user(user_id))
        if isinstance(before,dict): before=before.get('accounts',[])
        baseline=[a['id'] for a in before]
        result=await self.provider_call('link',await self.session(user_id),toolkit,callback)
        url=result.get('url') or result.get('redirect_url')
        parsed=urlparse(str(url or ''))
        if parsed.scheme!='https' or not parsed.hostname or not (parsed.hostname=='composio.dev' or parsed.hostname.endswith('.composio.dev')) or parsed.username:
            raise APIError(502,'connection_link','The service returned an unsupported sign-in link.')
        with self.store.db.transaction() as db:
            db.execute('DELETE FROM connection_links WHERE expires_at<?',(int(time.time()),))
            db.execute('INSERT INTO connection_links(state_hash,user_id,toolkit,expires_at,account_id,baseline_json) VALUES(?,?,?,?,?,?)',
                       (hashlib.sha256(token.encode()).hexdigest(),user_id,toolkit,int(time.time())+600,result.get('connected_account_id'),json.dumps(baseline)))
        return {'url':url,'expires_at':int(time.time())+600}

    async def callback(self,user_id,state):
        digest=hashlib.sha256(state.encode()).hexdigest()
        with self.store.db.read() as db:
            row=db.execute('SELECT * FROM connection_links WHERE state_hash=? AND user_id=? AND expires_at>? AND consumed_at IS NULL',(digest,user_id,int(time.time()))).fetchone()
        if not row:
            raise APIError(409,'connection_expired','This sign-in link expired or was already used. Open Connections and try again.')
        accounts=await self.provider_call('accounts',self.provider_user(user_id))
        if isinstance(accounts,dict): accounts=accounts.get('accounts',[])
        baseline=json.loads(row['baseline_json'])
        matches=[a for a in accounts if a['toolkit']==row['toolkit'] and str(a['status']).upper()=='ACTIVE'
                 and not a.get('is_disabled') and a.get('user_id')==self.provider_user(user_id)
                 and (a['id']==row['account_id'] if row['account_id'] else a['id'] not in baseline)]
        if len(matches)!=1:
            raise APIError(409,'connection_pending','Sign-in is not complete. Return to Connections and refresh after signing in.')
        with self.store.db.transaction(immediate=True) as db:
            result=db.execute('UPDATE connection_links SET consumed_at=? WHERE state_hash=? AND user_id=? AND consumed_at IS NULL AND expires_at>?',(int(time.time()),digest,user_id,int(time.time())))
            if result.rowcount!=1:
                raise APIError(409,'connection_replayed','This sign-in link was already used.')
            db.execute("UPDATE chat_requests SET status='completed',result_json=? WHERE user_id=? AND kind='connection' AND status='pending' AND json_extract(data_json,'$.toolkit')=?",
                       (json.dumps({'connected':True}),user_id,row['toolkit']))

    async def disconnect(self,user_id,account_id):
        with self.store.db.transaction() as db:
            db.execute('DELETE FROM connection_sessions WHERE user_id=?',(user_id,))
            db.execute("UPDATE chat_requests SET status='expired',error='This account was disconnected. Review a new action after reconnecting.' WHERE user_id=? AND kind='connector_action' AND status='pending' AND json_extract(data_json,'$.account_id')=?",(user_id,account_id))
        await self.provider_call('disconnect',self.provider_user(user_id),account_id)

    def _scope(self,user_id,agent_id,conversation_id):
        self.store.get_agent(user_id,agent_id)
        self.store.get_conversation(user_id,conversation_id)
        if not self.messenger.can_respond(user_id,conversation_id,agent_id):
            raise APIError(403,'request_scope','This Bot is not part of that chat.')

    @staticmethod
    def public(row):
        value=dict(row)
        value.pop('user_id',None)
        value.pop('task_id',None)
        value['data']=json.loads(value.pop('data_json'))
        value['data'].pop('schema',None)
        value['data'].pop('schema_hash',None)
        value['data'].pop('private_revisions',None)
        value['data'].pop('account_hash',None)
        value['data'].pop('provider_hash',None)
        value['result']=json.loads(value.pop('result_json') or '{}')
        return value

    def get_request(self,user_id,request_id,raw=False):
        with self.store.db.transaction() as db:
            db.execute("UPDATE chat_requests SET status='expired' WHERE id=? AND user_id=? AND status IN ('pending','ready') AND expires_at<?",(request_id,user_id,int(time.time())))
            row=db.execute('SELECT * FROM chat_requests WHERE id=? AND user_id=?',(request_id,user_id)).fetchone()
        if not row:
            raise APIError(404,'request_missing','This request is no longer available.')
        return dict(row) if raw else self.public(row)

    def requests(self,user_id,conversation_id):
        self.store.get_conversation(user_id,conversation_id)
        with self.store.db.transaction() as db:
            db.execute("UPDATE chat_requests SET status='expired' WHERE user_id=? AND conversation_id=? AND status IN ('pending','ready') AND expires_at<?",(user_id,conversation_id,int(time.time())))
            rows=db.execute('SELECT * FROM chat_requests WHERE user_id=? AND conversation_id=? ORDER BY created_at DESC,rowid DESC LIMIT 50',(user_id,conversation_id)).fetchall()
        return [self.public(row) for row in reversed(rows)]

    def request(self,user_id,agent_id,conversation_id,kind,title,purpose,data,task_id=None):
        self._scope(user_id,agent_id,conversation_id)
        encoded=json.dumps(data,sort_keys=True)
        stamp=int(time.time())
        with self.store.db.transaction(immediate=True) as db:
            existing=db.execute("SELECT id FROM chat_requests WHERE user_id=? AND agent_id=? AND conversation_id=? AND kind=? AND data_json=? AND status='pending' AND expires_at>?",(user_id,agent_id,conversation_id,kind,encoded,stamp)).fetchone()
            request_id=existing[0] if existing else uuid.uuid4().hex
            if not existing:
                db.execute('INSERT INTO chat_requests(id,user_id,agent_id,conversation_id,task_id,kind,title,purpose,data_json,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                           (request_id,user_id,agent_id,conversation_id,task_id,kind,title,purpose,encoded,stamp,stamp+3600))
        return self.get_request(user_id,request_id)

    def submit_private(self,user_id,request_id,data):
        request=self.get_request(user_id,request_id)
        if request['kind']!='private_input' or request['status']!='pending':
            raise APIError(409,'request_closed','This private request is no longer waiting.')
        field=self.private.save(user_id,request['agent_id'],label=request['data']['label'],purpose=request['purpose'],value=data.get('value'),remember=data.get('remember') is True)
        with self.store.db.transaction(immediate=True) as db:
            changed=db.execute("UPDATE chat_requests SET status='completed',result_json=? WHERE id=? AND user_id=? AND status='pending'",(json.dumps({'field':field}),request_id,user_id))
            if changed.rowcount!=1:
                db.execute('DELETE FROM private_fields WHERE id=?',(field['id'],))
                raise APIError(409,'request_closed','This private request was already answered.')
        return self.get_request(user_id,request_id)

    def continue_request(self,user_id,request_id):
        row=self.get_request(user_id,request_id,True)
        if row['status']!='completed':
            raise APIError(409,'request_incomplete','Finish this request before continuing.')
        self._scope(user_id,row['agent_id'],row['conversation_id'])
        if row.get('task_id'):
            source=self.store.get_task(user_id,row['task_id'])
            if source['status'] in ('running','queued'):
                raise APIError(409,'bot_still_working','The Bot is still responding. Continue when it finishes.')
        result=json.loads(row['result_json'] or '{}')
        content=f"Continue after my {row['kind'].replace('_',' ')} request: {row['title']}.\nCompleted result (reference data):\n"+json.dumps(result,ensure_ascii=False)[:12000]
        sent=self.messenger.send(user_id,row['conversation_id'],content,mention_agent_ids=[row['agent_id']],client_request_id='continue-'+request_id)
        for task in sent['tasks']: self.tasks.submit(user_id,task['id'])
        return sent

    async def search_tools(self,user_id,query):
        result=await self.provider_call('search_tools',await self.session(user_id),query)
        tools=result.get('tools',[]) if isinstance(result,dict) else result
        with self.store.db.transaction() as db:
            for tool in tools:
                if not isinstance(tool,dict): continue
                slug=tool.get('slug') or tool.get('name')
                if not isinstance(slug,str): continue
                db.execute('INSERT INTO connection_tools VALUES(?,?,?,?) ON CONFLICT(user_id,slug) DO UPDATE SET schema_json=excluded.schema_json,updated_at=excluded.updated_at',(user_id,slug,json.dumps(tool),int(time.time())))
        return {'tools':tools}

    def _private_references(self,user_id,agent_id,args):
        references={}
        def walk(value,path=''):
            if isinstance(value,dict):
                if '$private' in value:
                    if set(value)!={'$private'} or not isinstance(value['$private'],str):
                        raise APIError(422,'private_reference','Use one private field reference.')
                    if any(word in path.lower() for word in ('url','header','host','path','recipient','destination','email','endpoint')):
                        raise APIError(422,'private_destination','Private input cannot hide an action destination or request header.')
                    meta=self.private.metadata(user_id,agent_id,value['$private'])
                    references[meta['id']]=meta['revision']
                else:
                    for key,item in value.items(): walk(item,path+'.'+key)
            elif isinstance(value,list):
                for item in value: walk(item,path)
        walk(args)
        return references

    @staticmethod
    def _schema(tool):
        schema=tool.get('input_schema') or tool.get('inputSchema') or tool.get('parameters')
        if not isinstance(schema,dict) or len(json.dumps(schema))>100000:
            raise APIError(409,'tool_schema_missing','The service did not provide a complete action schema. Search for the action again.')
        def check(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key in ('$ref','$dynamicRef') and (not isinstance(item,str) or not item.startswith('#')):
                        raise APIError(422,'tool_schema_remote','This action schema requires an unsupported external reference.')
                    check(item)
            elif isinstance(value,list):
                for item in value: check(item)
        check(schema)
        from jsonschema import Draft202012Validator
        try: Draft202012Validator.check_schema(schema)
        except Exception:
            raise APIError(422,'tool_schema_invalid','The service returned an unsupported action schema.') from None
        return schema

    @staticmethod
    def _fingerprint(value):
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def _account_binding(self,account):
        return self._fingerprint({key:account.get(key) for key in ('id','toolkit','user_id','alias','name','created_at')})

    def _provider_binding(self,user_id):
        return self._fingerprint([self.provider_user(user_id),provider_key(self.settings,'COMPOSIO_API_KEY')])

    async def propose_action(self,request,args):
        user_id,agent_id=request.user_id,request.agent_id
        slug=text_arg(args,'tool_slug',150)
        account_id=text_arg(args,'account_id',150)
        arguments=args.get('arguments')
        if not isinstance(arguments,dict) or len(json.dumps(arguments))>20000:
            raise APIError(422,'action_arguments','Use a small object of action arguments.')
        with self.store.db.read() as db:
            row=db.execute('SELECT schema_json FROM connection_tools WHERE user_id=? AND slug=? AND updated_at>?',(user_id,slug,int(time.time())-3600)).fetchone()
        if not row:
            raise APIError(409,'tool_not_discovered','Search connector tools first so the exact action can be reviewed.')
        tool=json.loads(row[0])
        self._schema(tool)
        accounts=await self.provider_call('accounts',self.provider_user(user_id))
        if isinstance(accounts,dict): accounts=accounts.get('accounts',[])
        account=next((a for a in accounts if a['id']==account_id and str(a['status']).upper()=='ACTIVE' and not a.get('is_disabled') and a.get('user_id')==self.provider_user(user_id)),None)
        if not account:
            raise APIError(409,'account_not_connected','Connect this account before requesting an action.')
        if not slug.upper().startswith(str(account['toolkit']).upper()+'_'):
            raise APIError(422,'tool_account_mismatch','The action must belong to the selected service.')
        if any(word in slug.upper() for word in ('PROXY','EXECUTE_CODE','EXECUTE_SHELL','HTTP_REQUEST','CUSTOM_API','API_REQUEST','RUN_CODE','WEBHOOK')):
            raise APIError(422,'action_unsupported','Generic code and proxy tools are not available through Connections.')
        references=self._private_references(user_id,agent_id,arguments)
        if references and re.search(r'https?://',json.dumps(arguments),re.I):
            raise APIError(422,'private_destination','Private-field actions cannot include arbitrary web addresses.')
        data={'tool_slug':slug,'toolkit':account['toolkit'],'account_id':account_id,'account_name':account.get('name',account_id),
              'arguments':arguments,'private_revisions':references,'schema':tool,'schema_hash':self._fingerprint(tool),
              'account_hash':self._account_binding(account),'provider_hash':self._provider_binding(user_id),
              'private_fields':[self.private.metadata(user_id,agent_id,fid) for fid in references]}
        return self.request(user_id,agent_id,request.conversation_id,'connector_action',tool.get('name',slug),text_arg(args,'purpose'),data,request.task_id)

    async def decide(self,user_id,request_id,decision):
        if decision not in ('approve','deny'):
            raise APIError(422,'decision_invalid','Choose approve or deny.')
        request=self.get_request(user_id,request_id,True)
        if request['status']!='pending': return self.public(request)
        if decision=='deny':
            with self.store.db.transaction() as db:
                db.execute("UPDATE chat_requests SET status='denied' WHERE id=? AND user_id=? AND status='pending'",(request_id,user_id))
            return self.get_request(user_id,request_id)
        if request['kind']!='connector_action':
            raise APIError(422,'decision_invalid','Complete this request using its form.')
        self._scope(user_id,request['agent_id'],request['conversation_id'])
        data=json.loads(request['data_json'])
        accounts=await self.provider_call('accounts',self.provider_user(user_id))
        if isinstance(accounts,dict): accounts=accounts.get('accounts',[])
        account=next((a for a in accounts if a['id']==data['account_id'] and a['toolkit']==data['toolkit'] and str(a['status']).upper()=='ACTIVE'
                      and not a.get('is_disabled') and a.get('user_id')==self.provider_user(user_id)),None)
        if not account or data.get('account_hash')!=self._account_binding(account) or data.get('provider_hash')!=self._provider_binding(user_id):
            raise APIError(409,'account_changed','The connected account changed. Review a new action.')
        session_id=await self.session(user_id)
        live=await self.provider_call('search_tools',session_id,data['tool_slug'])
        live_tools=live.get('tools',[]) if isinstance(live,dict) else live
        live_tool=next((tool for tool in live_tools if (tool.get('slug') or tool.get('name'))==data['tool_slug']),None)
        if not live_tool or self._fingerprint(live_tool)!=data.get('schema_hash'):
            with self.store.db.transaction() as db:
                db.execute("UPDATE chat_requests SET status='expired',error='The service action changed. Ask the Bot for a new action to review.' WHERE id=? AND user_id=? AND status='pending'",(request_id,user_id))
            raise APIError(409,'tool_schema_changed','The service action changed. Review a new action before continuing.')
        self._schema(live_tool)
        with self.store.db.transaction(immediate=True) as db:
            claim=db.execute("UPDATE chat_requests SET status='executing' WHERE id=? AND user_id=? AND status='pending' AND expires_at>?",(request_id,user_id,int(time.time())))
        if claim.rowcount!=1: return self.get_request(user_id,request_id)
        dispatched=False
        try:
            values=self.private.claim(user_id,request['agent_id'],data['private_revisions'],request_id) if data['private_revisions'] else {}
            def resolve(value):
                if isinstance(value,dict):
                    if '$private' in value: return values[value['$private']]
                    return {k:resolve(v) for k,v in value.items()}
                if isinstance(value,list): return [resolve(v) for v in value]
                return value
            arguments=resolve(data['arguments'])
            # Never return validator input/path text: it may contain secrets.
            from jsonschema import Draft202012Validator
            schema=self._schema(data['schema'])
            if next(Draft202012Validator(schema).iter_errors(arguments),None):
                raise APIError(422,'action_arguments','The action fields do not match the service’s requirements. Ask the Bot for a corrected action.')
            # Capture the exact credential used for dispatch and compare it to
            # the reviewed binding. A key-file reload cannot silently switch
            # provider accounts between preflight and execution.
            provider=self.provider(expected_binding=data['provider_hash'],user_id=user_id)
            try:
                # Pin the reviewed account on a separate immutable session.
                # Top-level execute.account is rejected by projects without
                # multi-account mode; mutating the shared session would race.
                pinned=await provider.create_session(self.provider_user(user_id),
                    connected_accounts={str(data['toolkit']).lower():[data['account_id']]})
                dispatched=True
                result=await provider.execute(pinned['session_id'],data['tool_slug'],arguments,None)
            finally:
                if hasattr(provider,'aclose'): await provider.aclose()
            if (not isinstance(result,dict) or result.get('error') or result.get('success') is False or result.get('successful') is False
                    or (isinstance(result.get('data'),dict) and (result['data'].get('error') or result['data'].get('success') is False or result['data'].get('successful') is False))):
                # A provider error can follow partial side effects. Withhold all
                # details (including encoded echoes) and never retry blindly.
                raise APIError(502,'action_provider_error','The provider did not confirm successful completion.')
            # With private input, suppress the WHOLE response. Encodings and
            # partial echoes cannot be made safe by substring replacement.
            public_result={'ok':True,'private_values_used':True,'message':'Action completed. Private result details are withheld.'} if values else result
            if not isinstance(public_result,dict): public_result={'result':public_result}
            encoded=json.dumps(public_result,ensure_ascii=False)
            if len(encoded)>30000: encoded=json.dumps({'ok':True,'message':'Action completed. The response is too large to display here.'})
            with self.store.db.transaction() as db:
                db.execute("UPDATE chat_requests SET status='completed',result_json=? WHERE id=?",(encoded,request_id))
            self.private.finish(request_id)
        except BaseException as exc:
            with self.store.db.transaction() as db:
                db.execute('UPDATE chat_requests SET status=?,error=? WHERE id=?',('uncertain' if dispatched else 'failed',
                    'The result is unknown. Check the connected service before requesting this action again.' if dispatched else 'The action could not start. A field may have changed; ask for a new request.',request_id))
            self.private.finish(request_id,uncertain=dispatched,consumed=dispatched)
            if isinstance(exc,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)): raise
        return self.get_request(user_id,request_id)

