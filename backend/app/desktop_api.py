"""Small authenticated lifecycle additions; existing desktop routes stay intact."""
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field


class DesktopControl(BaseModel):
    mode: Literal["manual", "bot"]


class DesktopHeartbeat(BaseModel):
    generation: int = Field(ge=0)
    visible: bool
    viewer_token: str | None = Field(default=None, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


def register_desktop_routes(api, *, store, desktop, current_session, require_origin):
    @api.post("/agents/{agent_id}/desktop/control")
    async def control(agent_id: str, body: DesktopControl,
                      session=Depends(current_session), _=Depends(require_origin)):
        store.get_agent(session.user_id, agent_id)
        if desktop is None:
            raise HTTPException(503, "Computer service is unavailable")
        return {"desktop": await desktop.control(agent_id, body.mode, viewer_id=session.id)}

    @api.post("/agents/{agent_id}/desktop/heartbeat")
    async def heartbeat(agent_id: str, body: DesktopHeartbeat,
                        session=Depends(current_session), _=Depends(require_origin)):
        store.get_agent(session.user_id, agent_id)
        if desktop is None:
            raise HTTPException(503, "Computer service is unavailable")
        return {"desktop": await desktop.heartbeat(agent_id, body.generation, body.visible, viewer_id=session.id + (":" + body.viewer_token if body.viewer_token else ""))}

