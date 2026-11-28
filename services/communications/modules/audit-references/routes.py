"""Owner-mediated operational references with independent failure boundaries."""
import asyncio
import os
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from bt_bulkheads import DependencyClient, Unavailable
from bt_runtime.principal import current_principal, require_scope
from bt_contracts.comms.audit_references.models import AuditQuery, AuditReference, OwnerPage, Source

router = APIRouter(prefix='/v1/audit-references', tags=['audit references'])
SOURCES = ('trust', 'orders', 'service-operations')


def clients(app):
    if not hasattr(app.state, 'audit_reference_clients'):
        app.state.audit_reference_clients = {
            name: DependencyClient(name, os.getenv('BT_' + name.upper().replace('-', '_') + '_URL',
                'http://' + name + ':8000'), timeout=0.8, concurrency=4 if name == 'identity' else 2)
            for name in ('identity', *SOURCES)
        }
    return app.state.audit_reference_clients


def bearer(request):
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    return token


async def principal(request: Request):
    try:
        p = await current_principal(clients(request.app)['identity'], bearer(request), request.state.request_id)
    except (ValueError, TypeError, KeyError):
        raise HTTPException(503) from None
    if isinstance(p, Unavailable):
        raise HTTPException(503)
    if 'operator' not in p.roles:
        raise HTTPException(403)
    return p


def scope(p, organization):
    require_scope(p, 'audit.references.read', organization)


def headers(request):
    return {'Authorization': 'Bearer ' + bearer(request), 'X-Request-ID': request.state.request_id}


async def owner_read(request, source, path, params):
    try:
        async with asyncio.timeout(0.9):
            answer = await clients(request.app)[source].request('GET', path, params=params, headers=headers(request))
        if isinstance(answer, Unavailable):
            return 'unavailable', None
        state = {202: 'pending', 401: 'denied', 403: 'denied', 409: 'stale'}.get(answer.status_code)
        if state:
            return state, None
        if answer.status_code != 200 or len(answer.content) > 262144:
            return 'unavailable', None
        return 'ready', answer
    except (TimeoutError, ValueError, TypeError, KeyError):
        return 'unavailable', None


async def source_page(request, source, q, p):
    state, answer = await owner_read(request, source, '/internal/v1/audit-references', q.model_dump(mode='json', exclude_none=True))
    if answer is None:
        return {'source': source, 'state': state, 'page': None}
    try:
        page = OwnerPage.model_validate_json(answer.content)
        if page.query != q or page.reader_id != p.actor.subject_id:
            raise ValueError('Reader or query mismatch')
        return {'source': source, 'state': 'ready' if page.items else 'empty', 'page': page.model_dump(mode='json')}
    except ValueError:
        return {'source': source, 'state': 'unavailable', 'page': None}


async def read_query(request: Request):
    values = dict(request.query_params)
    values.pop('source', None)
    if len(request.query_params) > 13 or any(len(value) > 512 for value in values.values()) or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params):
        raise HTTPException(422)
    for key in ('limit', 'offset', 'expected_revision'):
        if key in values:
            if not values[key].isascii() or not values[key].isdigit() or len(values[key]) > 16:
                raise HTTPException(422)
            values[key] = int(values[key])
    try:
        return AuditQuery.model_validate_json(json.dumps(values))
    except ValueError:
        raise HTTPException(422) from None


@router.get('')
async def listing(request: Request, response: Response, source: Source | None = None, q: AuditQuery = Depends(read_query), p=Depends(principal)):
    scope(p, q.organization_id)
    results = await asyncio.gather(*(source_page(request, source, q, p) for source in ((source,) if source else SOURCES)))
    # Recheck authority after outstanding owner calls, including revoked membership.
    fresh = await principal(request)
    scope(fresh, q.organization_id)
    if fresh.actor != p.actor:
        raise HTTPException(403)
    response.headers['Cache-Control'] = 'no-store'
    return {'schema_version': 'audit-references.v1', 'operation_id': str(q.operation_id), 'results': results}


@router.get('/operations/{operation_id}')
async def lookup(operation_id: UUID, request: Request, response: Response, source: Source,
                 organization_id: UUID, expected_revision: int = Query(ge=1, le=9007199254740991), p=Depends(principal)):
    scope(p, organization_id)
    state, answer = await owner_read(request, source, '/internal/v1/audit-references/operations/' + str(operation_id),
        {'organization_id': str(organization_id), 'expected_revision': expected_revision})
    item = None
    if answer is not None:
        try:
            parsed = AuditReference.model_validate_json(answer.content)
            if parsed.operation_id != operation_id or parsed.organization_id != organization_id:
                raise ValueError('Operation scope mismatch')
            if parsed.revision != expected_revision:
                state = 'stale'
            else:
                item = parsed.model_dump(mode='json')
        except ValueError:
            state = 'unavailable'
    fresh = await principal(request)
    scope(fresh, organization_id)
    if fresh.actor != p.actor:
        raise HTTPException(403)
    response.headers['Cache-Control'] = 'no-store'
    return {'schema_version': 'audit-references.v1', 'source': source, 'state': state, 'item': item}


async def run(app, stop):
    upstream = clients(app)
    try:
        await stop.wait()
    finally:
        for client in upstream.values():
            await client.aclose()
