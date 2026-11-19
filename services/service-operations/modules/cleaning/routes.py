"""Additive route factory; composition supplies current authenticated sources."""
import asyncio
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends
from bt_contracts.service.cleaning.v1 import Command, Facts
from bt_contracts_core.errors import PublicError
from .domain import Denied, authority, readiness


def make_router(store, provider, principal, clock=lambda: datetime.now(timezone.utc)):
    router = APIRouter(prefix='/v1/cleaning', tags=['external cleaning'])

    async def current(p, subject, action):
        try:
            async with asyncio.timeout(2):
                async with provider.current(p, subject) as raw:
                    facts = Facts.model_validate(raw)
                    authority(facts, p.actor.subject_id, subject)
                    if facts.quote and (facts.quote.request_id != subject
                            or facts.quote.buyer_id != facts.actor_id
                            or facts.quote.watch_id != facts.watch_id
                            or facts.quote.organization_id != facts.organization_id):
                        raise Denied('denied')
                    return await action(facts)
        except Denied as error:
            status = 403 if error.code == 'denied' else 409
            raise PublicError(error.code, 'Review the current request. / راجع الطلب الحالي.', status=status) from None
        except (TimeoutError, OSError, ValueError):
            raise PublicError('unavailable', 'Try again later. / حاول مجدداً لاحقاً.', status=503) from None

    @router.post('/requests/{subject_id}')
    async def command(subject_id: UUID, body: Command, p=Depends(principal)):
        if body.subject_id != subject_id or body.actor_id != p.actor.subject_id:
            raise PublicError('denied', 'Access denied. / الوصول مرفوض.', status=403)
        async def apply(facts):
            if body.organization_id != facts.organization_id or body.watch_id != facts.watch_id:
                raise Denied('denied')
            return await store.apply(body, facts, clock)
        return await current(p, subject_id, apply)

    @router.get('/requests/{subject_id}')
    async def read(subject_id: UUID, p=Depends(principal)):
        async def load(facts):
            record = await store.read(subject_id)
            if record and (record.actor_id != facts.actor_id or record.organization_id != facts.organization_id
                           or record.watch_id != facts.watch_id):
                raise Denied('denied')
            return {'record': record, 'quote': facts.quote,
                    'binding': {'schema_version': 'cleaning.v1', 'subject_id': subject_id,
                                'actor_id': facts.actor_id, 'organization_id': facts.organization_id,
                                'watch_id': facts.watch_id, 'source_revision': facts.source_revision,
                                'policy_revision': facts.policy_revision}}
        return await current(p, subject_id, load)

    @router.get('/operations/{operation_id}')
    async def lookup(operation_id: UUID, subject_id: UUID, p=Depends(principal)):
        async def load(facts):
            result = await store.lookup(operation_id, facts.actor_id, subject_id)
            if result and (result.organization_id != facts.organization_id or result.watch_id != facts.watch_id):
                raise Denied('denied')
            return {'result': result, 'state': 'recorded' if result else 'unknown'}
        return await current(p, subject_id, load)

    @router.get('/requests/{subject_id}/readiness')
    async def execution(subject_id: UUID, p=Depends(principal)):
        async def load(facts):
            return readiness(await store.read(subject_id), facts, clock())
        return await current(p, subject_id, load)

    return router
