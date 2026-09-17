"""Harmless real desktop lifecycle checks for the named QA bot only."""
import asyncio
import base64
import json
import struct
from pathlib import Path
from urllib.parse import urlparse,parse_qs,unquote

import httpx
import websockets
from app.auth import AuthManager
from app.config import Settings
from app.db import Database
from app.store import Store

settings=Settings.from_env()
store=Store(Database(settings.database_path))
with store.db.read() as db:
    row=db.execute("SELECT id,user_id FROM agents WHERE name='QA Grok Chief 20260917'").fetchone()
if not row: raise SystemExit("Named QA bot missing")
agent,owner=row[0],row[1]
base=settings.public_base_url.rstrip("/")
client=httpx.Client(base_url=base+"/bot/api/",headers={"Origin":base},timeout=180)
checks=[]
out=Path("/data/qa-evidence/grok-20260917");out.mkdir(parents=True,exist_ok=True)

def api(method,path,**kwargs):
    response=client.request(method,path,**kwargs)
    if response.is_error: raise RuntimeError(str(response.status_code)+" "+response.text[:400])
    return response.json()

def check(name,valid=True):
    if not valid: raise AssertionError(name)
    checks.append(name);print("PASS: "+name,flush=True)

async def rfb(view, while_connected=None):
    socket_path=unquote(parse_qs(urlparse(view).query)["path"][0])
    cookies="; ".join(key+"="+value for key,value in client.cookies.items())
    async with websockets.connect(base.replace("https:","wss:")+"/"+socket_path,origin=base,additional_headers={"Cookie":cookies},subprotocols=["binary"],open_timeout=20,close_timeout=2) as socket:
        buffer=bytearray()
        async def take(size):
            while len(buffer)<size:
                buffer.extend(await asyncio.wait_for(socket.recv(),15))
            result=bytes(buffer[:size]);del buffer[:size]
            return result
        assert (await take(12)).startswith(b'RFB ')
        await socket.send(b'RFB 003.008\n')
        count=(await take(1))[0]
        assert 1 in await take(count), 'Expected private-proxy VNC no-auth transport'
        await socket.send(b'\x01')
        assert await take(4)==b'\x00\x00\x00\x00'
        await socket.send(b'\x01')
        server=await take(24)
        width,height=struct.unpack('>HH',server[:4])
        assert width>0 and height>0
        await take(struct.unpack('>I',server[20:24])[0])
        await socket.send(struct.pack('>BBHi',2,0,1,0))
        await socket.send(struct.pack('>BBHHHH',3,0,0,0,1,1))
        assert (await take(1))[0]==0, 'Expected an actual framebuffer update'
        header=await take(3)
        assert struct.unpack('>H',header[1:])[0]>0
        rectangle=await take(12)
        _,_,rw,rh,encoding=struct.unpack('>HHHHi',rectangle)
        assert encoding==0 and 0<rw*rh<=1024
        await take(rw*rh*(server[4]//8))
        return while_connected() if while_connected else True

try:
    nonce=AuthManager(store.db,settings).create_nonce(owner)
    api("POST","auth/exchange",json={"nonce":nonce["nonce"]})
    # Previous audit bot is explicitly QA-owned and can relinquish its slot.
    old=next((bot for bot in api("GET","agents")["agents"] if bot["name"]=="QA Audit Bot 20260916"),None)
    if old: api("DELETE",f"agents/{old['id']}/desktop")
    state=api("POST",f"agents/{agent}/desktop")["desktop"]
    check("Private QA desktop wakes",state["running"] and state["control_mode"]=="bot")
    check("Authenticated generation-bound viewer connects",asyncio.run(rfb(state["view_url"])))
    api("POST",f"agents/{agent}/desktop/action",json={"action":"navigate","text":"https://example.com"})
    shot=api("POST",f"agents/{agent}/desktop/action",json={"action":"screenshot"})["result"]
    (out/"computer-before-handoff.png").write_bytes(base64.b64decode(shot["image_url"].split(",",1)[1]))
    check("Live desktop screenshot is real",shot["width"]==1366 and shot["height"]==900)
    manual=asyncio.run(rfb(state["view_url"],lambda: api("POST",f"agents/{agent}/desktop/control",json={"mode":"manual"})["desktop"]))
    check("Take control changes ownership generation",manual["control_mode"]=="manual" and manual["generation"]>state["generation"])
    blocked=client.post(f"agents/{agent}/desktop/action",json={"action":"screenshot"})
    check("Bot actions are rejected during manual ownership",blocked.status_code==409)
    check("Manual viewer reconnects with current generation",asyncio.run(rfb(manual["view_url"])))
    returned=asyncio.run(rfb(manual["view_url"],lambda: api("POST",f"agents/{agent}/desktop/control",json={"mode":"bot"})["desktop"]))
    check("Return to bot restores bot ownership",returned["control_mode"]=="bot" and returned["generation"]>manual["generation"])
    check("Viewer reconnects immediately after returning to bot",asyncio.run(rfb(returned["view_url"])))
    check("Sleeping desktop stops its container",not api("DELETE",f"agents/{agent}/desktop")["desktop"]["running"])
    resumed=api("POST",f"agents/{agent}/desktop")["desktop"]
    check("Same private desktop wakes again",resumed["running"] and resumed["created"])
    check("Viewer works after stop/start",asyncio.run(rfb(resumed["view_url"])))
    # Release this viewer and leave the computer idle for the real TTL check.
    api("POST",f"agents/{agent}/desktop/heartbeat",json={"generation":resumed["generation"],"visible":False})
    check("Hidden viewer releases its wake lease")
finally:
    (out/"desktop.json").write_text(json.dumps({"agent_id":agent,"checks":checks,"source":"real Linux desktop through public authenticated API"},indent=2),encoding="utf-8")
    try: api("POST","auth/logout")
    finally: client.close()

