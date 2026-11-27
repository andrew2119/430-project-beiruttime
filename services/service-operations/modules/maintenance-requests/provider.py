"""Request-scoped ownership, destination and private-reference authority."""
from uuid import UUID, uuid4
from io import BytesIO
from PIL import Image
from bt_contracts.service.maintenance.v1 import AdmissionAuthority, Context
from fastapi import HTTPException
from bt_bulkheads import Unavailable
from bt_runtime.principal import current_principal
from bt_runtime.app.db import unit_of_work
from service_app.sources import client, bearer, official_business, prerequisite
from .commands import AdmissionSnapshot


async def identity(request):
    value = await current_principal(client(request, 'identity'), bearer(request), request.state.request_id)
    if isinstance(value, Unavailable):
        raise HTTPException(503)
    if value.actor.organization_id is not None or 'buyer' not in value.roles:
        raise HTTPException(403)
    return value.actor.subject_id


class Provider:
    def __init__(self, request):
        self.request = request

    async def context(self, actor, watch):
        try:
            facts = Context.model_validate(await prerequisite(self.request, 'maintenance_context', actor, watch))
        except ValueError:
            raise ConnectionError('maintenance_context_unavailable') from None
        if (facts.actor_id, facts.subject_id, facts.watch_id) != (actor, actor, watch):
            raise HTTPException(403)
        return facts.model_dump(mode='json')

    async def admission(self, actor, watch, organization, operation, intervention):
        try:
            return AdmissionAuthority.model_validate(await prerequisite(
                self.request, 'maintenance_admission', actor, watch, organization, operation, intervention))
        except ValueError:
            raise ConnectionError('maintenance_authority_unavailable') from None

    async def current(self, body):
        facts = await self.admission(body.actor_id, body.watch_id, body.organization_id,
                                     body.operation_id, body.intervention)
        live_revision = None
        if facts.business_active:
            business = await official_business(self.request, body.organization_id, 'servicing')
            live_revision = business.get('revision')
            if type(live_revision) is not int or live_revision < 1:
                raise ConnectionError('maintenance_capability_unavailable')
        async with self.request.app.state.pool.acquire() as tx:
            rows = await tx.fetch('''SELECT id FROM maintenance_photos WHERE actor_id=$1 AND watch_id=$2
                AND organization_id=$3 AND request_operation_id=$4''', body.actor_id, body.watch_id, body.organization_id, body.operation_id)
        return AdmissionSnapshot(**facts.model_dump(), live_capability_revision=live_revision,
            private_refs_current=set(body.photo_refs) <= {row['id'] for row in rows}).model_dump(mode='json')

    async def operation_access(self, actor, organization, operation, watch, intervention):
        facts = await self.admission(actor, watch, organization, operation, intervention)
        return (facts.identity_current and facts.watch_owned
                and (facts.actor_id, facts.subject_id, facts.watch_id, facts.organization_id,
                     facts.operation_id, facts.intervention)
                == (actor, actor, watch, organization, operation, intervention))

    async def store_photo(self, actor, body, content):
        context = await self.context(actor, body.watch_id)
        if UUID(context['actor_id']) != actor or not any(UUID(row['organization_id']) == body.organization_id for row in context['destinations']):
            raise HTTPException(403)
        try:
            with Image.open(BytesIO(content)) as image:
                if image.width * image.height > 16000000 or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('invalid_image')
                image.load()
                mode = 'RGB' if body.media_type == 'image/jpeg' else 'RGBA'
                converted = image.convert(mode)
                clean = Image.frombytes(mode, converted.size, converted.tobytes())
                output = BytesIO()
                clean.save(output, format={'image/jpeg':'JPEG','image/png':'PNG','image/webp':'WEBP'}[body.media_type])
                encoded = output.getvalue()
                if len(encoded) > 262144:
                    raise ValueError('invalid_image')
        except (OSError, Image.DecompressionBombError):
            raise ValueError('invalid_image') from None
        async with unit_of_work(self.request.app.state.pool, lock_key=f'maintenance-photo:{actor}:{body.request_operation_id}') as tx:
            prior = await tx.fetchrow('SELECT * FROM maintenance_photos WHERE operation_id=$1', body.operation_id)
            if prior:
                if (prior['actor_id'],prior['watch_id'],prior['organization_id'],prior['request_operation_id'],prior['content']) != (actor,body.watch_id,body.organization_id,body.request_operation_id,encoded):
                    raise ValueError('operation_conflict')
                return prior['id']
            if await tx.fetchval('SELECT count(*) FROM maintenance_photos WHERE actor_id=$1 AND request_operation_id=$2', actor, body.request_operation_id) >= 10:
                raise ValueError('photo_limit')
            reference = uuid4()
            await tx.execute('INSERT INTO maintenance_photos VALUES($1,$2,$3,$4,$5,$6,$7)', reference, body.operation_id, actor, body.watch_id, body.organization_id, body.request_operation_id, encoded)
            return reference
