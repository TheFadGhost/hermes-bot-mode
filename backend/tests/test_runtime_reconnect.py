import asyncio
from types import SimpleNamespace

from app.codex_runtime import CodexRuntime


def test_running_runtime_recovers_when_signin_bridge_was_late(tmp_path,monkeypatch):
    monkeypatch.setenv("BOT_HERMES_AUTH_BRIDGE","true")
    async def scenario():
        runtime=CodexRuntime(tmp_path)
        runtime.proc=SimpleNamespace(returncode=None)
        attempts=0
        async def credentials(force_refresh=False):
            nonlocal attempts
            attempts+=1
            if attempts==1: raise OSError("Bridge still starting")
            return {"accessToken":"fixture","chatgptAccountId":"fixture"}
        async def rpc(method,params,timeout=45):
            assert method=="account/login/start"
            return {}
        async def refresh():
            runtime.account={"type":"chatgpt"}
        runtime._hermes_credentials=credentials
        runtime.rpc=rpc
        runtime.refresh_account=refresh
        await runtime.start()
        assert not runtime.status().available
        await runtime.start()
        assert attempts==1  # bounded retry rate
        runtime._last_bridge_attempt=0
        await runtime.start()
        assert runtime.status().available and attempts==2
        runtime.db.close()
    asyncio.run(scenario())

