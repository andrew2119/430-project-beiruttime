"""Bounded request admission with transaction-owned receipts and public-safe events."""
import asyncio
import hashlib
import json
from uuid import uuid4
from pydantic import Field, StrictInt
from bt_contracts.service.maintenance.v1 import RequestAuthority

class AdmissionSnapshot(RequestAuthority):
    live_capability_revision: StrictInt | None = Field(default=None, ge=1)


class Rejected(ValueError):
    pass

async def submit(body, *, actor_id, provider, transaction):
    if actor_id != body.actor_id or body.actor_id != body.subject_id:
        raise Rejected('denied')
    if body.expected_revision != 0:
        raise Rejected('stale')
    if not body.limited_assessment_permission:
        raise Rejected('assessment_permission_required')
    # The provider must recheck identity, ownership, current business capability,
    # exclusive watch commitment and access to every private reference.
    try:
        facts = await asyncio.wait_for(provider.current(body), timeout=1.2)
    except (TimeoutError, ConnectionError):
        raise Rejected('pending') from None
    try:
        facts = AdmissionSnapshot.model_validate(facts).model_dump()
    except ValueError:
        raise Rejected('pending') from None
    if not all(facts.get(k) is True for k in ('identity_current','watch_owned','business_active',
            'assessment_supported','commitment_available','private_refs_current')):
        raise Rejected('denied')
    if any(facts.get(key) != getattr(body, key) for key in
            ('actor_id', 'subject_id', 'watch_id', 'organization_id', 'brand_id', 'intervention', 'operation_id')):
        raise Rejected('denied')
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()
    async with transaction(body.operation_id) as tx:
        prior = await tx.fetchrow('SELECT request_hash,result FROM maintenance_request_operations WHERE operation_id=$1', body.operation_id)
        if prior:
            if prior['request_hash'] != digest:
                raise Rejected('operation_conflict')
            return json.loads(prior['result'])
        live_revision = facts['live_capability_revision']
        if live_revision is not None and live_revision != facts['capability_revision']:
            raise Rejected('stale')
        if (facts.get('watch_revision'), facts.get('capability_revision'), facts.get('policy_revision')) != (body.watch_revision, body.capability_revision, body.policy_revision):
            raise Rejected('stale')
        request_id = uuid4()
        result = {k: str(getattr(body,k)) for k in ('operation_id','subject_id','watch_id','actor_id','organization_id')}
        result.update(schema_version='service.maintenance.v1', expected_revision=0,
            request_id=str(request_id), watch_revision=body.watch_revision,
            capability_revision=body.capability_revision, policy_revision=body.policy_revision, state='submitted', revision=1,
            pending_reason=None, next_actor='business', next_review_at=None)
        await tx.execute('INSERT INTO maintenance_requests(id,operation_id,actor_id,organization_id,watch_id,private_request) VALUES($1,$2,$3,$4,$5,$6::jsonb)',
            request_id, body.operation_id, body.actor_id, body.organization_id, body.watch_id, body.model_dump_json())
        # No symptoms, photographs or private evidence references leave this module.
        await tx.execute('INSERT INTO maintenance_request_outbox(event_id,request_id,event_type) VALUES($1,$2,$3)',
            body.operation_id, request_id, 'service-operations.maintenance.submitted.v1')
        await tx.execute('INSERT INTO maintenance_request_operations(operation_id,actor_id,organization_id,request_hash,result) VALUES($1,$2,$3,$4,$5::jsonb)',
            body.operation_id, body.actor_id, body.organization_id, digest, json.dumps(result))
        return result

async def lookup(operation_id, *, actor_id, organization_id, tx):
    return await tx.fetchrow(
        """SELECT receipt.result, request.watch_id, request.private_request->>'intervention' AS intervention
           FROM maintenance_request_operations receipt
           JOIN maintenance_requests request USING (operation_id, actor_id, organization_id)
           WHERE receipt.operation_id=$1 AND receipt.actor_id=$2 AND receipt.organization_id=$3""",
        operation_id, actor_id, organization_id)
