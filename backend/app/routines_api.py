from typing import Any
from fastapi import Depends, Request
from .errors import APIError

def register_routine_routes(api: Any, *, routines: Any, current_session: Any, require_origin: Any) -> None:
    async def body(request: Request) -> dict:
        value = await request.json()
        if not isinstance(value,dict):
            raise APIError(422,"routine_invalid","Routine details must be an object")
        return value

    @api.get("/agents/{agent_id}/routines")
    async def list_routines(agent_id: str, session=Depends(current_session)):
        return {"routines":routines.list(session.user_id,agent_id)}

    @api.post("/agents/{agent_id}/routines",status_code=201)
    async def create(agent_id: str, request: Request, session=Depends(current_session),_=Depends(require_origin)):
        return {"routine":routines.save(session.user_id,agent_id,await body(request))}

    @api.patch("/routines/{routine_id}")
    async def update(routine_id: str, request: Request, session=Depends(current_session),_=Depends(require_origin)):
        item = routines.get(session.user_id,routine_id)
        return {"routine":routines.save(session.user_id,item["agent_id"],await body(request),routine_id)}

    @api.delete("/routines/{routine_id}")
    async def remove(routine_id: str, session=Depends(current_session),_=Depends(require_origin)):
        routines.archive(session.user_id,routine_id)
        return {"archived":True}

    @api.post("/routines/{routine_id}/run",status_code=202)
    async def run(routine_id: str, request: Request, session=Depends(current_session),_=Depends(require_origin)):
        values = await body(request)
        return routines.run(session.user_id,routine_id,client_request_id=values.get("client_request_id"))

