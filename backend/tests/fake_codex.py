"""Protocol fixture, never used by the shipped application."""
import json
import sys

counter = 0
waiting = {}


def send(value):
    print(json.dumps(value), flush=True)


def finish(thread, turn):
    send({"method": "item/agentMessage/delta", "params": {"threadId": thread, "delta": "fixture reply"}})
    send({"method": "turn/completed", "params": {"threadId": thread, "turn": {"id": turn, "status": "completed"}}})


for line in sys.stdin:
    msg = json.loads(line)
    method, params = msg.get("method"), msg.get("params", {})
    if method is None:
        state = waiting.pop(msg["id"], None)
        if state:
            finish(*state)
        continue
    if "id" not in msg:
        continue
    result = {}
    # Thread setup uses kebab-case SandboxMode, unlike turn sandboxPolicy.
    if method in {"thread/start", "thread/resume"} and params.get("sandbox") not in {"read-only", "workspace-write", "danger-full-access"}:
        send({"id": msg["id"], "error": {"code": -32602, "message": "Invalid SandboxMode"}})
        continue
    if method == "account/read":
        result = {"account": {"type": "chatgpt", "planType": "plus"}}
    elif method == "model/list":
        result = {"data": [{"model": "gpt-5.6-luna"}]}
    elif method == "thread/start":
        counter += 1
        result = {"thread": {"id": f"thread-{counter}"}}
    elif method == "thread/resume":
        result = {"thread": {"id": params["threadId"]}}
    elif method == "turn/start":
        thread, turn = params["threadId"], "turn-1"
        send({"id": msg["id"], "result": {"turn": {"id": turn}}})
        if params["input"][0]["text"] == "approval":
            waiting["approval-1"] = (thread, turn)
            send({"id": "approval-1", "method": "item/commandExecution/requestApproval", "params": {"threadId": thread, "turnId": turn, "command": "echo example"}})
        else:
            finish(thread, turn)
        continue
    send({"id": msg["id"], "result": result})

