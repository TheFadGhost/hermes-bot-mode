"""Authenticated web endpoints for connections, private input and teaching."""
from __future__ import annotations
import asyncio
import json
from fastapi import Depends, Request, Query
from starlette.responses import RedirectResponse
from starlette.requests import Request as ParsedRequest
from .errors import APIError
from .private_fields import provider_key
from .extension_service import text_arg


async def bounded_body(request,limit):
    value=bytearray()
    async for chunk in request.stream():
        value.extend(chunk)
        if len(value)>limit:
            raise APIError(413,'request_too_large','This request is too large.')
    return bytes(value)


async def body_json(request):
    try:
        value=json.loads(await bounded_body(request,65536))
    except (ValueError,UnicodeDecodeError):
        raise APIError(422,'invalid_json','Use a valid form request.') from None
    if not isinstance(value,dict):
        raise APIError(422,'invalid_json','Use a form object.')
    return value


def register_extension_routes(api,*,extensions,current_session,require_origin):
    e=extensions
    voice_semaphore=asyncio.Semaphore(2)

    @api.get('/extensions/status')
    async def status(session=Depends(current_session)):
        return e.status()

    @api.get('/connections')
    async def connections(q:str=Query('',max_length=200),cursor:str=Query('',max_length=500),session=Depends(current_session)):
        return await e.connections(session.user_id,q,cursor)

    @api.post('/connections/link')
    async def link(request:Request,session=Depends(current_session),_=Depends(require_origin)):
        body=await body_json(request)
        return await e.link(session.user_id,text_arg(body,'toolkit',100))

    @api.get('/connections/callback')
    async def callback(state:str=Query(...,min_length=20,max_length=200),session=Depends(current_session)):
        await e.callback(session.user_id,state)
        return RedirectResponse('/bot/?connections=return',status_code=303)

    @api.delete('/connections/{account_id}')
    async def disconnect(account_id:str,session=Depends(current_session),_=Depends(require_origin)):
        await e.disconnect(session.user_id,account_id)
        return {'ok':True}

    @api.get('/conversations/{conversation_id}/requests')
    async def requests(conversation_id:str,session=Depends(current_session)):
        return {'requests':e.requests(session.user_id,conversation_id)}

    @api.post('/requests/{request_id}/private')
    async def private_answer(request_id:str,request:Request,session=Depends(current_session),_=Depends(require_origin)):
        return {'request':e.submit_private(session.user_id,request_id,await body_json(request))}

    @api.post('/requests/{request_id}/decision')
    async def decision(request_id:str,request:Request,session=Depends(current_session),_=Depends(require_origin)):
        body=await body_json(request)
        return {'request':await e.decide(session.user_id,request_id,body.get('decision'))}

    @api.post('/requests/{request_id}/continue')
    async def continue_request(request_id:str,session=Depends(current_session),_=Depends(require_origin)):
        return e.continue_request(session.user_id,request_id)

    @api.get('/agents/{agent_id}/private-fields')
    async def fields(agent_id:str,session=Depends(current_session)):
        return {'fields':e.private.list(session.user_id,agent_id)}

    @api.post('/agents/{agent_id}/private-fields')
    async def save_field(agent_id:str,request:Request,session=Depends(current_session),_=Depends(require_origin)):
        body=await body_json(request)
        return {'field':e.private.save(session.user_id,agent_id,label=body.get('label'),purpose=body.get('purpose',''),value=body.get('value'),remember=body.get('remember') is True)}

    @api.delete('/agents/{agent_id}/private-fields/{field_id}')
    async def remove_field(agent_id:str,field_id:str,session=Depends(current_session),_=Depends(require_origin)):
        e.private.delete(session.user_id,agent_id,field_id)
        return {'ok':True}

    @api.get('/agents/{agent_id}/teachings')
    async def teachings(agent_id:str,session=Depends(current_session)):
        return {'teachings':e.teachings.list(session.user_id,agent_id)}

    @api.post('/agents/{agent_id}/teachings')
    async def teach(agent_id:str,request:Request,session=Depends(current_session),_=Depends(require_origin)):
        return {'teaching':e.teachings.save(session.user_id,agent_id,await body_json(request))}

    @api.patch('/agents/{agent_id}/teachings/{teaching_id}')
    async def edit_teach(agent_id:str,teaching_id:str,request:Request,session=Depends(current_session),_=Depends(require_origin)):
        return {'teaching':e.teachings.save(session.user_id,agent_id,await body_json(request),teaching_id)}

    @api.delete('/agents/{agent_id}/teachings/{teaching_id}')
    async def delete_teach(agent_id:str,teaching_id:str,session=Depends(current_session),_=Depends(require_origin)):
        e.teachings.delete(session.user_id,agent_id,teaching_id)
        return {'ok':True}

    @api.post('/agents/{agent_id}/teachings/{teaching_id}/run')
    async def run_teach(agent_id:str,teaching_id:str,request:Request,session=Depends(current_session),_=Depends(require_origin)):
        body=await body_json(request)
        return e.teachings.run(session.user_id,agent_id,teaching_id,body.get('input',''),text_arg(body,'client_request_id',128))

    @api.post('/voice/transcribe')
    async def transcribe(request:Request,session=Depends(current_session),_=Depends(require_origin)):
        from .voice_provider import VoiceProvider
        key=provider_key(e.settings,'OPENROUTER_API_KEY')
        if not key:
            raise APIError(503,'voice_unconfigured','Dictation needs the administrator’s OpenRouter key first.')
        raw=await bounded_body(request,11*1024*1024)
        delivered=False
        async def receive():
            nonlocal delivered
            if delivered: return {'type':'http.disconnect'}
            delivered=True
            return {'type':'http.request','body':raw,'more_body':False}
        clone=ParsedRequest(request.scope,receive)
        async with clone.form(max_files=1,max_fields=2) as form:
            file=form.get('file')
            if not hasattr(file,'read'):
                raise APIError(422,'audio_missing','Record a voice note first.')
            audio=await file.read(10*1024*1024+1)
            mime=str(file.content_type or '').split(';')[0]
            formats={'audio/webm':'webm','video/webm':'webm','audio/ogg':'ogg','audio/mp4':'m4a','audio/m4a':'m4a','audio/wav':'wav','audio/x-wav':'wav','audio/mpeg':'mp3','audio/flac':'flac','audio/aac':'aac'}
            if mime not in formats:
                raise APIError(415,'audio_format','This browser’s audio format is unsupported.')
            if voice_semaphore.locked():
                raise APIError(429,'voice_busy','Two voice notes are already being transcribed. Try again shortly.')
            async with voice_semaphore:
                from .audio_probe import prepare_dictation
                normalized=await asyncio.to_thread(prepare_dictation,audio)
                async with VoiceProvider(key) as provider:
                    return await provider.transcribe(normalized,'wav')

