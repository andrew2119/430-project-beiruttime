"""Additive HTTP boundary; the runtime supplies current private scope adapters."""
from dataclasses import fields
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from .workflow import Change, Approval, Rejected


def router_for(workflow, principal):
    router = APIRouter()

    async def run(request, action):
        try:
            actor, organization = await principal(request)
            return await action(actor, organization)
        except Rejected as error:
            code = str(error)
            status = 403 if code == 'denied' else 404 if code == 'not_found' else 409
            return JSONResponse({'code': code}, status_code=status)
        except (TimeoutError, ConnectionError):
            return JSONResponse({'code': 'unavailable'}, status_code=503)

    async def body(request, model):
        # Bound raw input before decoding; no files or evidence are accepted.
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 8192:
                raise Rejected('request_too_large')
        import json
        try:
            value = json.loads(data)
            if not isinstance(value, dict) or set(value) - {f.name for f in fields(model)}:
                raise Rejected('invalid_body')
            return model(**value)
        except (ValueError, TypeError):
            raise Rejected('invalid_body') from None

    @router.get('/v1/jobs/{subject_id}/change-review')
    async def review(subject_id: str, request: Request):
        async def action(actor, organization):
            # Provider returns only current authorized review text and bindings.
            return await workflow.call('review', subject_id, actor, organization)
        return await run(request, action)

    @router.post('/v1/jobs/{subject_id}/changes')
    async def start(subject_id: str, request: Request):
        async def action(actor, organization):
            command = await body(request, Change)
            if command.subject_id != subject_id:
                raise Rejected('stale_scope')
            return await workflow.start(command, actor, organization)
        return await run(request, action)

    @router.get('/v1/job-change-operations/{operation_id}')
    async def lookup(operation_id: str, request: Request):
        return await run(request, lambda actor, organization: workflow.lookup(operation_id, actor, organization))

    @router.post('/v1/job-change-operations/{operation_id}/resume')
    async def resume(operation_id: str, request: Request):
        return await run(request, lambda actor, organization: workflow.resume(operation_id, actor, organization))

    @router.post('/v1/job-change-operations/{operation_id}/accept')
    async def accept(operation_id: str, request: Request):
        async def action(actor, organization):
            from dataclasses import replace
            approval = await body(request, Approval)
            # Acceptance is stamped by the authoritative server clock.
            approval = replace(approval, accepted_at=workflow.clock())
            return await workflow.accept(operation_id, approval, actor, organization)
        return await run(request, action)

    return router
