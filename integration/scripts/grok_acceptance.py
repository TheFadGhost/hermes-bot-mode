"""Live acceptance against the public API, using explicitly named QA data."""
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
import websockets
from app.auth import AuthManager
from app.config import Settings
from app.db import Database
from app.store import Store

settings=Settings.from_env()
store=Store(Database(settings.database_path))
with store.db.read() as db:
    owner_row=db.execute("SELECT user_id FROM agents WHERE name='QA Audit Bot 20260916'").fetchone()
if not owner_row:
    raise SystemExit("Named QA owner anchor missing")
owner=owner_row[0]
base=settings.public_base_url.rstrip("/")
client=httpx.Client(base_url=base+"/bot/api/",headers={"Origin":base},timeout=200)
report={"phase":sys.argv[1],"checks":[],"source":"live-public-api"}
out=Path("/data/qa-evidence/grok-20260917")
out.mkdir(parents=True,exist_ok=True)

def api(method,path,**kwargs):
    response=client.request(method,path,**kwargs)
    if response.is_error:
        raise RuntimeError(f"{method} {path}: {response.status_code} {response.text[:400]}")
    return response.json()

def check(name,condition=True):
    if not condition: raise AssertionError(name)
    report["checks"].append(name)
    print("PASS: "+name,flush=True)

def bot(name):
    existing=next((agent for agent in api("GET","agents")["agents"] if agent["name"]==name),None)
    if existing:
        if existing["status"]!="active":
            existing=api("PATCH","agents/"+existing["id"],json={"status":"active"})["agent"]
        return existing
    return api("POST","agents",json={"name":name,"instructions":"You are a QA test assistant. Follow exact harmless test instructions. Be concise.","color":"#2d93fa","avatar":"blob"})["agent"]

def wait(task_id,timeout=360):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        task=api("GET","tasks/"+task_id)["task"]
        if task["status"] in {"completed","failed","cancelled"}:
            if task["status"]!="completed": raise RuntimeError(str(task.get("error")))
            return task
        time.sleep(2)
    raise TimeoutError("QA task timeout")

try:
    nonce=AuthManager(store.db,settings).create_nonce(owner)
    api("POST","auth/exchange",json={"nonce":nonce["nonce"]})
    lead=bot("QA Grok Chief 20260917")
    helper=bot("QA Grok Scout 20260917")
    home=api("GET",f"agents/{lead['id']}/home")["conversation"]
    phase=sys.argv[1]
    if phase=="messaging":
        check("One stable home per bot",api("POST","conversations",json={"agent_id":lead["id"],"title":"No duplicate thread"})["conversation"]["id"]==home["id"])
        chief=api("POST","bootstrap")["chief"]
        check("Chief bootstrap is idempotent",api("POST","bootstrap")["chief"]["id"]==chief["id"])
        groups=api("GET","inbox")["items"]
        group=next((item for item in groups if item["name"]=="QA Grok Group 20260917"),None)
        if not group:
            group=api("POST","groups",json={"name":"QA Grok Group 20260917","agent_ids":[lead["id"],helper["id"]]})["conversation"]
        content=b"The QA shared itinerary reference is CALDER-9937."
        file=api("POST","files",data={"agent_id":lead["id"]},files={"file":("qa-group-itinerary-"+uuid.uuid4().hex[:8]+".txt",content,"text/plain")})["file"]
        payload={"content":"Use files_read with the attached file_id to read the itinerary. Reply with its exact reference and no other text.","file_ids":[file["id"]],"mention_agent_ids":[lead["id"],helper["id"]],"client_request_id":str(uuid.uuid4())}
        result=api("POST",f"conversations/{group['id']}/messages",json=payload)
        repeated=api("POST",f"conversations/{group['id']}/messages",json=payload)
        check("Retry creates no duplicate message or responders",result["message"]["id"]==repeated["message"]["id"] and [t["id"] for t in result["tasks"]]==[t["id"] for t in repeated["tasks"]])
        for task in result["tasks"]: wait(task["id"])
        messages=api("GET",f"conversations/{group['id']}/messages")["messages"]
        replies=[m for m in messages if m.get("request_id")==result["request_id"] and m["role"]=="assistant"]
        check("Both group members read the explicitly shared file",len(replies)==2 and all("CALDER-9937" in m["content"] for m in replies))
        check("Both live replies retain distinct authors",{m["author_agent_id"] for m in replies}=={lead["id"],helper["id"]})
        hits=api("GET",f"conversations/{group['id']}/search",params={"q":"CALDER-9937"})["matches"]
        check("Search finds live exact replies",len(hits)>=2)
        exact=api("GET",f"conversations/{group['id']}/messages/{replies[0]['id']}")["message"]
        check("Exact message is readable",exact["content"]==replies[0]["content"])
        report.update(group_id=group["id"],lead_id=lead["id"],helper_id=helper["id"],conversation_id=home["id"])
    elif phase=="delegation":
        result=api("POST",f"conversations/{home['id']}/messages",json={"content":"Authorized QA: call delegate_task to ask QA Grok Scout 20260917 to reply with exactly HELPER-RETURN-4821. Do not poll colleague_result. Then reply only: Scout is helping.","client_request_id":str(uuid.uuid4())})
        wait(result["task"]["id"])
        deadline=time.monotonic()+300
        children=[]
        while time.monotonic()<deadline:
            tasks=api("GET",f"conversations/{home['id']}/tasks")["tasks"]
            children=[t for t in tasks if t.get("parent_task_id")==result["task"]["id"]]
            if children and all(t["status"]=="completed" for t in children): break
            time.sleep(2)
        check("Bot delegated real work to named colleague",len(children)==1)
        check("Helper finishes with independent runtime capacity",children[0]["status"]=="completed")
        messages=api("GET",f"conversations/{home['id']}/messages")["messages"]
        relays=[m for m in messages if m.get("source_task_id")==children[0]["id"]]
        check("Helper result returns once to original chat",len(relays)==1 and "HELPER-RETURN-4821" in relays[0]["content"])
        check("Handoff is visible",any(m.get("metadata",{}).get("collaboration_handoff") for m in messages))
    elif phase=="creation":
        if "--verify-existing" not in sys.argv:
            result=api("POST",f"conversations/{home['id']}/messages",json={"content":"Authorized QA: use create_bot to create a bot named QA Grok Librarian 20260917 with instructions 'Organize harmless QA notes concisely.' Then use group_create to create QA Library Group 20260917 with QA Grok Chief 20260917 and QA Grok Librarian 20260917. Reply briefly when both tools confirm success.","client_request_id":str(uuid.uuid4())})
            wait(result["task"]["id"])
        bots=api("GET","agents")["agents"]
        created=next((b for b in bots if b["name"]=="QA Grok Librarian 20260917"),None)
        check("Bot created a real specialist through scoped tool",created is not None)
        groups=api("GET","inbox")["items"]
        check("Bot created a real two-member group",any(g["kind"]=="group" and g["name"]=="QA Library Group 20260917" and len(g["members"])==2 for g in groups))
        desktop=api("GET",f"agents/{created['id']}/desktop")
        check("Creating a bot consumes no desktop slot",not desktop.get("created") and not desktop.get("running"))
    elif phase=="continuity":
        first=api("POST",f"conversations/{home['id']}/messages",json={"content":"For this harmless QA test, the old booking was CALDER-4821. Correction: the current booking is CALDER-9937. Please acknowledge briefly.","client_request_id":str(uuid.uuid4())})
        wait(first["task"]["id"])
        api("POST",f"conversations/{home['id']}/compact",json={"reason":"QA continuity verification"})
        check("Real runtime compaction completed")
        question=api("POST",f"conversations/{home['id']}/messages",json={"content":"Use history_search and then history_read to verify my current CALDER booking reference from the original message. Return only the current reference.","client_request_id":str(uuid.uuid4())})
        wait(question["task"]["id"])
        messages=api("GET",f"conversations/{home['id']}/messages")["messages"]
        replies=[m for m in messages if m.get("source_task_id")==question["task"]["id"]]
        check("Corrected fact recalled after real compaction",len(replies)==1 and "CALDER-9937" in replies[0]["content"] and "CALDER-4821" not in replies[0]["content"])
        original=api("GET",f"conversations/{home['id']}/messages/{first['message']['id']}")["message"]
        check("Original chat remains intact and readable",original["content"]==first["message"]["content"])
        with store.db.read() as db:
            metrics=db.execute("SELECT recent_chars,retrieval_chars FROM context_records WHERE task_id=?",(question["task"]["id"],)).fetchone()
        report["context_chars"]={"recent":metrics[0],"retrieved":metrics[1]}
        check("Working context is bounded",metrics[0]<=14000 and metrics[1]<=6000)
    elif phase=="routines":
        item=api("POST",f"agents/{lead['id']}/routines",json={"name":"QA paused briefing","instruction":"Reply exactly ROUTINE-READY-17.","time":"08:00","timezone":"Europe/London","weekdays":[0,1,2,3,4],"enabled":False})["routine"]
        request={"client_request_id":str(uuid.uuid4())}
        result=api("POST",f"routines/{item['id']}/run",json=request)
        replay=api("POST",f"routines/{item['id']}/run",json=request)
        check("Run now retries reuse one task",result["task"]["id"]==replay["task"]["id"])
        wait(result["task"]["id"])
        messages=api("GET",f"conversations/{home['id']}/messages")["messages"]
        check("Routine result appears in continuing chat",any(m.get("source_task_id")==result["task"]["id"] and "ROUTINE-READY-17" in m["content"] for m in messages))
        api("DELETE",f"routines/{item['id']}")
        check("QA routine removed safely",not any(r["id"]==item["id"] for r in api("GET",f"agents/{lead['id']}/routines")["routines"]))
    elif phase=="cleanup":
        names={'QA Grok Chief 20260917','QA Grok Scout 20260917','QA Grok Librarian 20260917','QA Grok Group 20260917','QA Library Group 20260917'}
        entries=api('GET','inbox',params={'include_archived':'true'})['items']
        archived=[]
        for item in entries:
            if item['name'] not in names: continue
            check('QA chat has no active work: '+item['name'],not item.get('active_tasks'))
            api('POST',f"conversations/{item['conversation_id']}/archive")
            archived.append(item['name'])
        report['archived_qa_chats']=archived
        chief=next((item for item in entries if item['name']=='Chief' and item['kind']=='direct'),None)
        if chief: api('POST',f"conversations/{chief['conversation_id']}/pin",params={'pinned':'true'})
        check('QA history kept in Archived chats',len(archived)==5)
    elif phase=="interface_contract":
        generic=api("GET","search",params={"q":"CALDER"})['matches']
        check("CALDER keyword returns real archive matches",bool(generic))
        matches=api("GET","search",params={"q":"CALDER-9937"})['matches']
        check("Global chat search returns real messages",bool(matches) and all(item.get('message_id') and item.get('conversation_id') for item in matches))
        exact=api("GET",f"messages/{matches[0]['message_id']}")['message']
        check("Search exact-message endpoint preserves content",'CALDER-9937' in exact['content'])
        page=api("GET",f"conversations/{home['id']}/messages",params={'limit':1})['messages']
        earlier=api("GET",f"conversations/{home['id']}/messages",params={'limit':1,'before_id':page[0]['id']})['messages']
        check("History cursor reads an earlier distinct message",len(page)==len(earlier)==1 and page[0]['id']!=earlier[0]['id'])
        account=api("GET","runtime/account")
        connected=account.get('account',account).get('connected')
        check("Runtime account reconnects after deployment",connected is True)
    elif phase=="learning":
        group=next(item for item in api("GET","inbox")["items"] if item["name"]=="QA Grok Group 20260917")
        result=api("POST",f"conversations/{group['id']}/messages",json={"content":"Authorized QA: use history_search for CALDER in this group, then history_read to confirm the original attached itinerary discussion. After verifying the tool outputs, use skills_save to save a procedure named qa verify itinerary history, with concise steps for verifying an itinerary from original chat history and the actual observed evidence. Then reply briefly. Do not use any other bot or browser.","mention_agent_ids":[helper['id']],"client_request_id":str(uuid.uuid4())})
        wait(result['task']['id'])
        from app.learned_skills import LearnedSkills
        learned=LearnedSkills(store)
        saved=[item for item in learned.list(owner,helper['id']) if item['name']=='qa verify itinerary history']
        check("Group responder saves a procedure after successful work",len(saved)==1 and saved[0]['state']=='ready')
        check("Procedure stays private to its responding bot",not any(item['name']=='qa verify itinerary history' for item in learned.list(owner,lead['id'])))
    elif phase=="cancel":
        group=next(item for item in api("GET","inbox")["items"] if item["name"]=="QA Grok Group 20260917")
        result=api("POST",f"conversations/{group['id']}/messages",json={"content":"Write a lengthy explanation of prime numbers.","mention_agent_ids":[lead["id"],helper["id"]],"client_request_id":str(uuid.uuid4())})
        stopped=api("POST",f"conversations/{group['id']}/requests/{result['request_id']}/cancel")["tasks"]
        check("Stop cancels both group responders",len(stopped)==2 and all(t["status"]=="cancelled" for t in stopped))
        time.sleep(3)
        check("Cancelled tasks remain terminal",all(api("GET","tasks/"+t["id"])["task"]["status"]=="cancelled" for t in stopped))
    else:
        raise ValueError("Unknown phase")
    report["passed"]=True
finally:
    (out/(report["phase"]+".json")).write_text(json.dumps(report,indent=2),encoding="utf-8")
    try: api("POST","auth/logout")
    finally: client.close()

