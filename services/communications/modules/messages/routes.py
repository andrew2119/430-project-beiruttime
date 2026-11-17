"""Versioned adapters. Missing composition remains unavailable, never synthetic success."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from bt_bulkheads import Unavailable
from bt_runtime.principal import current_principal
from .domain import Denied, bounded, integer

router = APIRouter(prefix='/v1/messages', tags=['messages'])


async def principal(request: Request):
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise Denied('sign_in', 401)
    try:
        result = await asyncio.wait_for(current_principal(request.app.state.identity, token, request.state.request_id), 2)
    except (TimeoutError, ValueError, TypeError):
        raise Denied('source_unavailable', 503) from None
    if isinstance(result, Unavailable):
        raise Denied('source_unavailable', 503)
    return result.actor


async def actor(request: Request):
    try:
        return await principal(request)
    except Denied as error:
        from fastapi import HTTPException
        raise HTTPException(error.status, detail={'code': error.code}) from None


def composition(request):
    store = getattr(request.app.state, 'messages_store', None)
    provider = getattr(request.app.state, 'messages_authority', None)
    if store is None or provider is None:
        raise Denied('source_unavailable', 503)
    return store, provider


async def source(provider, method, *args):
    try:
        return await asyncio.wait_for(getattr(provider, method)(*args), 2)
    except Denied:
        raise
    except (TimeoutError, ConnectionError, ValueError, TypeError, AttributeError):
        raise Denied('source_unavailable', 503) from None


def failure(error):
    return JSONResponse({'schema_version': 'communications.messages.v1', 'state': 'unavailable' if error.status == 503 else 'stale' if error.status == 409 else 'denied', 'code': error.code, 'error': {'code': error.code}}, status_code=error.status, headers={'Cache-Control': 'no-store'})


def scope(owner):
    return str(owner.subject_id), str(owner.organization_id) if owner.organization_id else None


@router.get('/threads')
async def threads(request: Request, cursor: int = 0, limit: int = 20, owner=Depends(actor)):
    try:
        integer(cursor)
        integer(limit, 1, 50)
        store, provider = composition(request)
        person, organization = scope(owner)
        page = await source(provider, 'listing', person, organization, cursor, limit)
        if len(page['items']) > limit:
            raise Denied('source_unavailable', 503)
        # Listing authority supplies current scoped snapshots, not private bodies.
        items = []
        for snapshot in page['items']:
            facts = snapshot['authority']
            if facts.get('actor_id') != person or facts.get('organization_id') != organization or facts.get('state') != 'authorized' or not facts.get('current_member'):
                raise Denied('scope')
            thread = store.provision(snapshot)
            store.status(thread['id'], person, organization, facts, datetime.now(timezone.utc))
            items.append(thread)
        return {'items': items, 'total': integer(page['total']), 'next_cursor': page['next_cursor']}
    except Denied as error:
        return failure(error)


@router.post('/threads')
async def open_thread(request: Request, owner=Depends(actor)):
    try:
        # Body contains only an owning record, never participants or permission flags.
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 2048:
                raise Denied('invalid_request', 422)
        import json
        body = json.loads(raw)
        if not isinstance(body, dict) or set(body) != {'subject_id', 'kind'} or body['kind'] not in ('listing', 'order', 'business'):
            raise Denied('invalid_request', 422)
        bounded(body['subject_id'])
        store, provider = composition(request)
        person, organization = scope(owner)
        snapshot = await source(provider, 'open', person, organization, body['kind'], body['subject_id'])
        thread = store.provision(snapshot)
        store.status(thread['id'], person, organization, snapshot['authority'], datetime.now(timezone.utc))
        return thread
    except (ValueError, KeyError, TypeError):
        return failure(Denied('invalid_request', 422))
    except Denied as error:
        return failure(error)


@router.get('/threads/{thread_id}')
async def read(thread_id: str, request: Request, cursor: int = 0, limit: int = 20, owner=Depends(actor)):
    try:
        store, provider = composition(request)
        person, organization = scope(owner)
        facts = await source(provider, 'current', person, organization, bounded(thread_id))
        return store.read(thread_id, person, organization, facts, datetime.now(timezone.utc), cursor, limit)
    except Denied as error:
        return failure(error)


@router.get('/threads/{thread_id}/operations/{operation_id}')
async def lookup(thread_id: str, operation_id: str, request: Request, owner=Depends(actor)):
    try:
        store, provider = composition(request)
        person, organization = scope(owner)
        facts = await source(provider, 'current', person, organization, bounded(thread_id))
        return store.lookup(thread_id, person, organization, facts, datetime.now(timezone.utc), operation_id)
    except Denied as error:
        return failure(error)


@router.post('/threads/{thread_id}/commands')
async def command(thread_id: str, request: Request, owner=Depends(actor)):
    try:
        # Bound the actual stream as well as declared length, before decoding.
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 24576:
                raise Denied('invalid_request', 422)
        import json
        body = json.loads(raw)
        store, provider = composition(request)
        person, organization = scope(owner)
        facts = await source(provider, 'current', person, organization, bounded(thread_id))
        return store.command(thread_id, person, organization, facts, datetime.now(timezone.utc), body)
    except (ValueError, TypeError):
        return failure(Denied('invalid_request', 422))
    except Denied as error:
        return failure(error)


@router.get('/threads/{thread_id}/delivery')
async def delivery(thread_id: str, request: Request, owner=Depends(actor)):
    try:
        store, provider = composition(request)
        person, organization = scope(owner)
        facts = await source(provider, 'current', person, organization, bounded(thread_id))
        return store.delivery(thread_id, person, organization, facts, datetime.now(timezone.utc))
    except Denied as error:
        return failure(error)


@router.get('/threads/{thread_id}/status')
async def status(thread_id: str, request: Request, owner=Depends(actor)):
    try:
        store, provider = composition(request)
        person, organization = scope(owner)
        facts = await source(provider, 'current', person, organization, bounded(thread_id))
        return store.status(thread_id, person, organization, facts, datetime.now(timezone.utc))
    except Denied as error:
        return failure(error)
