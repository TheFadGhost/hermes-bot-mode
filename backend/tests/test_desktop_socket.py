import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from test_backend import make_settings, login, create_agent_and_conversation


class DesktopFixture:
    async def proxy_websocket(self, agent_id, websocket):
        await websocket.accept(subprotocol="binary")
        await websocket.send_bytes(b"RFB 003.008\n")
        await websocket.close()


def test_desktop_socket_requires_owner_and_origin(tmp_path):
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, desktop=DesktopFixture())) as client:
        login(client, settings)
        agent, _ = create_agent_and_conversation(client)
        path = f"/bot/api/agents/{agent}/desktop/view/websockify"
        with client.websocket_connect(path, headers={"Origin": "http://testserver"}, subprotocols=["binary"]) as socket:
            assert socket.receive_bytes().startswith(b"RFB ")
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(path, headers={"Origin": "https://other.example"}):
                pass
        login(client, settings, "another-owner")
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(path, headers={"Origin": "http://testserver"}):
                pass

