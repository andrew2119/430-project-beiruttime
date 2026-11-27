"""Bounded request admission with transaction-owned receipts and public-safe events."""
import asyncio
import hashlib
import json
from uuid import UUID, uuid4
from bt_contracts.service.maintenance.v1 import RequestAuthority

from .photos import attach

class Rejected(ValueError):
    pass

async def submit(body, *, actor_id, provider, transaction):
    if actor_id != body.actor_id or body.actor_id != body.subject_id:
        raise Rejected('denied')
    if body.expected_revision != 0:
        raise Rejected('stale')
    if not body.limited_assessment_permission:
        raise Rejected('assessment_permission_required')
    if len(body.photo_refs) != len(set(body.photo_refs)):
        raise Rejected('denied')
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    async with transaction(body.operation_id) as tx:
        prior = await tx.fetchrow('SELECT request_hash,result FROM maintenance_request_operations WHERE operation_id=$1', body.operation_id)
        # Receipt recovery requires present ownership, not a business still offering the service.
        if prior:
            retained = await lookup(body.operation_id, actor_id=actor_id, organization_id=body.organization_id,
                                    current_permission=True, tx=tx)
            if retained is None:
                raise Rejected('denied')
            try:
                allowed = await asyncio.wait_for(provider.operation_access(actor_id, body.organization_id,
                    body.operation_id, UUID(retained['watch_id']), retained['intervention'], UUID(retained['brand_id'])), timeout=1.2)
            except (TimeoutError, ConnectionError, ValueError, KeyError):
                raise Rejected('pending') from None
            if allowed is not True:
                raise Rejected('denied')
            if prior['request_hash'] != digest:
                raise Rejected('operation_conflict')
            return retained
        try:
            read = getattr(provider, 'current_with_photos', None)
            facts = await asyncio.wait_for(read(body, tx) if read else provider.current(body), timeout=1.2)
        except (TimeoutError, ConnectionError, ValueError):
            raise Rejected('pending') from None
        try:
            facts = RequestAuthority.model_validate(facts).model_dump()
        except ValueError:
            raise Rejected('pending') from None
        if not all(facts.get(k) is True for k in ('identity_current','watch_owned','private_refs_current')):
            raise Rejected('denied')
        if any(facts.get(key) != getattr(body, key) for key in
                ('actor_id', 'subject_id', 'watch_id', 'organization_id', 'brand_id', 'intervention', 'operation_id')):
            raise Rejected('denied')
        if not facts['business_active'] or not facts['assessment_supported']:
            raise Rejected('destination_ineligible')
        if not facts['commitment_available']:
            raise Rejected('watch_committed')
        if await tx.fetchval('''SELECT 1 FROM maintenance_closed_operations
                WHERE operation_id=$1 AND actor_id=$2 AND organization_id=$3''',
                body.operation_id, body.actor_id, body.organization_id):
            raise Rejected('operation_conflict')
        if (facts.get('watch_revision'), facts.get('capability_revision'), facts.get('policy_revision')) != (body.watch_revision, body.capability_revision, body.policy_revision):
            raise Rejected('stale')
        request_id = uuid4()
        result = {k: str(getattr(body,k)) for k in ('operation_id','subject_id','watch_id','actor_id','organization_id','brand_id')}
        result.update(schema_version='service.maintenance.v1', expected_revision=0,
            request_id=str(request_id), watch_revision=body.watch_revision,
            capability_revision=body.capability_revision, policy_revision=body.policy_revision, intervention=body.intervention, state='submitted', revision=1,
            pending_reason=None, next_actor='business', next_review_at=None)
        await tx.execute('INSERT INTO maintenance_requests(id,operation_id,actor_id,organization_id,watch_id,private_request) VALUES($1,$2,$3,$4,$5,$6::jsonb)',
            request_id, body.operation_id, body.actor_id, body.organization_id, body.watch_id, body.model_dump_json())
        if body.photo_refs and not await attach(tx, body, request_id):
            raise Rejected('photo_unavailable')
        # No symptoms, photographs or private evidence references leave this module.
        await tx.execute('INSERT INTO maintenance_request_outbox(event_id,request_id,event_type) VALUES($1,$2,$3)',
            body.operation_id, request_id, 'service-operations.maintenance.submitted.v1')
        await tx.execute('INSERT INTO maintenance_request_operations(operation_id,actor_id,organization_id,request_hash,result) VALUES($1,$2,$3,$4,$5::jsonb)',
            body.operation_id, body.actor_id, body.organization_id, digest, json.dumps(result))
        return result

async def lookup(operation_id, *, actor_id, organization_id, current_permission, tx):
    if not current_permission:
        raise Rejected('denied')
    row = await tx.fetchrow('''SELECT result || jsonb_build_object(
            'brand_id', r.private_request->'brand_id', 'intervention', r.private_request->'intervention') AS result
        FROM maintenance_request_operations o JOIN maintenance_requests r
          USING (operation_id, actor_id, organization_id)
        WHERE operation_id=$1 AND actor_id=$2 AND organization_id=$3''', operation_id, actor_id, organization_id)
    return json.loads(row['result']) if row else None
