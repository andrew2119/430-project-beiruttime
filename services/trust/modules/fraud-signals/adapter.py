"""Composition boundary: the host supplies authenticated, serialized source leases."""
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from .core import Rejected

STATUS = {'denied': 403, 'stale': 409, 'conflict': 409, 'invalid': 422, 'unavailable': 503}


@asynccontextmanager
async def lease(request, body):
    provider = getattr(request.app.state, 'fraud_signal_provider', None)
    store = getattr(request.app.state, 'fraud_signal_store', None)
    if provider is None or store is None:
        raise HTTPException(503, detail={'code': 'unavailable'})
    try:
        async with asyncio.timeout(1.2):
            async with provider.current(request, body) as snapshot:
                yield store, snapshot
    except (TimeoutError, ConnectionError):
        raise HTTPException(503, detail={'code': 'unavailable'}) from None
    except Rejected as error:
        raise HTTPException(STATUS[error.code], detail={'code': error.code}) from None
    except (KeyError, ValueError, TypeError, sqlite3.Error):
        raise HTTPException(503, detail={'code': 'unavailable'}) from None


def create_router(scan_type, photo_type, bid_type):
    router = APIRouter(prefix='/v1/fraud-signals', tags=['fraud-signals'])
    # Contract classes are supplied through the service's published module loader.
    @router.post('/scans')
    async def scan(request: Request):
        raw = bytearray()
        try:
            async with asyncio.timeout(1.2):
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 4096:
                        raise HTTPException(413, detail={'code': 'invalid'})
        except TimeoutError:
            raise HTTPException(503, detail={'code': 'unavailable'}) from None
        try:
            body = scan_type.model_validate(json.loads(raw)).model_dump(mode='json')
        except (ValueError, TypeError):
            raise HTTPException(422, detail={'code': 'invalid'}) from None
        async with lease(request, body) as (store, snapshot):
            try:
                if len(snapshot['photos']) > 500 or len(snapshot['bids']) > 5000:
                    raise Rejected('invalid')
                photos = [photo_type.model_validate(row).model_dump(mode='json') for row in snapshot['photos']]
                bids = [bid_type.model_validate_json(json.dumps(row)).model_dump(mode='json') for row in snapshot['bids']]
                return store.scan(body, snapshot['context'], photos, bids, datetime.now(timezone.utc))
            except (ValueError, KeyError, TypeError):
                raise HTTPException(503, detail={'code': 'unavailable'}) from None

    @router.get('/operations/{operation_id}')
    async def lookup(operation_id: str, request: Request):
        if len(operation_id) > 128:
            raise HTTPException(422, detail={'code': 'invalid'})
        async with lease(request, {'operation_id': operation_id}) as (store, snapshot):
            return store.lookup(operation_id, snapshot['context'], datetime.now(timezone.utc))

    @router.get('')
    async def page(request: Request, page: int = 1, page_size: int = 20):
        async with lease(request, None) as (store, snapshot):
            return store.page(snapshot['context'], datetime.now(timezone.utc), page, page_size)
    return router
