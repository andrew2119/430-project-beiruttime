"""Repair-only decisions over the retained Pricing journal and outbox."""
import json
from datetime import datetime
from contextlib import asynccontextmanager
from importlib import import_module
from uuid import UUID
from fastapi import Depends, Query, Request
from bt_contracts.pricing.quotes.assessed import AcceptQuote, DeclineQuote
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.app.db import unit_of_work
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.principal import require_scope
from service_app import peers
from service_app.assessed import access, build_router, current_source, load, project, event
from service_app.current import amounts, buyer, decoded, digest, replay, remember, require_usd
from service_app.security import idempotency

policy = import_module('bt_contracts.pricing.repair_quotes.policy')
current_scope, decision_binding = policy.current_scope, policy.decision_binding
recovery = import_module('bt_contracts.pricing.repair_quotes.recovery')

router = build_router('repair')
router.routes = [route for route in router.routes if not (
    ('POST' in route.methods and route.path.endswith(('/accept', '/decline')))
    or ('GET' in route.methods and route.path in ('/v1/repair-quotes', '/v1/repair-quotes/{quote_id}'))
)]


@asynccontextmanager
async def source_authorization(request, principal, snapshot, operation_key):
    """Require a source-owned fence held through decision commit before accepting."""
    raise PublicError('dependency_unavailable',
                      'Current repair authorization is unavailable; retry the same operation.', status=503)
    yield  # The source-owned serialized boundary is not available yet.


@asynccontextmanager
async def decision_authorization(request, principal, snapshot, operation_key, accepting):
    if accepting:
        async with source_authorization(request, principal, snapshot, operation_key) as source:
            current_scope(snapshot, source)
            yield
    else:
        yield


@asynccontextmanager
async def recovery_assignment(request, principal, snapshot, operation_key):
    """Reserve current responsibility through commit, using the original operation."""
    raise PublicError('dependency_unavailable',
                      'Return coordination is unavailable; retry the same operation.', status=503)
    yield


@asynccontextmanager
async def decision_recovery(request, principal, snapshot, operation_key, accepting):
    if accepting:
        yield None
        return
    async with recovery_assignment(request, principal, snapshot, operation_key) as value:
        try:
            assignment = recovery.RecoveryAssignment.model_validate(value)
            if (str(assignment.quote_id) != str(snapshot['id'])
                    or str(assignment.buyer_id) != str(snapshot['buyer_id'])
                    or str(assignment.organization_id) != str(snapshot['organization_id'])
                    or assignment.operation_id != operation_key):
                raise ValueError()
        except (ValueError, TypeError):
            raise PublicError('dependency_unavailable',
                              'Return coordination cannot be verified; retry the same operation.', status=503) from None
        yield assignment


def repair_projection(row, decision=None):
    result = project(row, decision)
    result['recovery'] = decoded(decision['repair_recovery']) if decision and decision.get('repair_recovery') else None
    if result['state'] == 'expired_return_held' and not result['recovery']:
        # A deadline is not a durable assignment or a custody transition.
        result['state'] = 'issued'
        result['return_coordination'] = 'unavailable'
    return result


async def recovery_event(tx, request, row, record):
    await enqueue(tx, EventEnvelope(
        type='pricing.repair-return.recovery-required.v1', source='pricing',
        subject=str(row['id']), request_id=request.state.request_id, data=record),
        ['repair-return-recovery-v1'])


async def decide(quote_id, body, request, p, key, *, accepting):
    buyer(p)
    fingerprint = digest(['repair', 'accept' if accepting else 'decline', str(quote_id), body.model_dump(mode='json')])
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
        row = await load(tx, quote_id, 'repair')
        if row['buyer_id'] != p.actor.subject_id:
            raise AccessDenied('Only the current quote buyer decides')
        if prior:
            return prior
    snapshot = decoded(row['snapshot'])
    require_usd(snapshot)
    if snapshot.get('policy', {}).get('revision') != 2:
        raise PublicError('legacy_reconciliation', 'Request a current USD quote.', status=409)
    # Declining cannot depend on a new diagnosis or imply permission to return custody.
    if accepting:
        current_scope(snapshot, await current_source(request, 'repair', snapshot))
    selected = sorted(str(value) for value in body.selected_line_ids) if accepting else []
    totals = amounts(snapshot['lines'], selected, snapshot['assessment_fee_minor']) if accepting else {}
    if accepting and totals['payable_minor'] != body.payable_minor:
        raise PublicError('quote_binding_mismatch', 'Review the exact selected total.', status=409)
    async with decision_authorization(request, p, snapshot, key, accepting), decision_recovery(
            request, p, snapshot, key, accepting) as assignment, unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
        if prior:
            return prior
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f"assessed:repair:{row['source_id']}")
        row = await load(tx, quote_id, 'repair', for_update=True)
        now = await tx.fetchval('SELECT clock_timestamp()')
        decision_binding(row, snapshot, body, accepting=accepting, now=now)
        state = 'accepted' if accepting else 'declined_return_held'
        fees = {'assessment': body.accept_assessment_fee, 'return_transport': body.accept_return_fee}
        await tx.execute('''INSERT INTO l14_quote_decisions(quote_id,actor_id,decision,selected_line_ids,amounts,terms_digest,decided_at,accepted_fee_lines)
            VALUES($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8::jsonb)''', quote_id, p.actor.subject_id, state,
            json.dumps(selected), json.dumps(totals), body.terms_digest, now, json.dumps(fees))
        held_recovery = recovery.recovery_record(assignment, now) if assignment else None
        if held_recovery:
            await tx.execute('UPDATE l14_quote_decisions SET repair_recovery=$2::jsonb WHERE quote_id=$1',
                             quote_id, json.dumps(held_recovery))
        row = await tx.fetchrow('UPDATE l14_assessed_quotes SET state=$2 WHERE id=$1 RETURNING *', quote_id, state)
        decision = await tx.fetchrow('SELECT * FROM l14_quote_decisions WHERE quote_id=$1', quote_id)
        await event(tx, request, row, 'accepted' if accepting else 'declined',
                    {'selected_line_ids': selected, 'total_minor': totals.get('payable_minor'),
                     'currency': 'USD', 'terms_digest': body.terms_digest})
        if held_recovery:
            await recovery_event(tx, request, row, held_recovery)
        return await remember(tx, p, key, fingerprint, {'status': 'succeeded', 'quote': repair_projection(row, decision)})


@router.post('/{quote_id}/accept')
async def accept(quote_id: UUID, body: AcceptQuote, request: Request,
                 p=Depends(peers.principal), key=Depends(idempotency)):
    return await decide(quote_id, body, request, p, key, accepting=True)


@router.post('/{quote_id}/decline')
async def decline(quote_id: UUID, body: DeclineQuote, request: Request,
                  p=Depends(peers.principal), key=Depends(idempotency)):
    return await decide(quote_id, body, request, p, key, accepting=False)


@router.get('')
async def listing(request: Request, page: int = Query(1, ge=1, le=1000000),
                  p=Depends(peers.principal)):
    org = p.actor.organization_id
    if org:
        require_scope(p, 'business.records.read', org)
    else:
        buyer(p)
    # One statement supplies a consistent page and total even while quotes change.
    async with request.app.state.pool.acquire() as tx:
        result = await tx.fetchrow('''WITH scoped AS MATERIALIZED (
            SELECT * FROM l14_assessed_quotes WHERE kind='repair' AND
            (($2::uuid IS NULL AND buyer_id=$1) OR organization_id=$2)
            AND snapshot->>'currency'='USD'
        ), page AS (
            SELECT * FROM scoped ORDER BY created_at DESC,id DESC LIMIT 20 OFFSET $3
        ) SELECT (SELECT count(*) FROM scoped) AS total,
            COALESCE((SELECT jsonb_agg(to_jsonb(page)) FROM page),'[]'::jsonb) AS rows''',
            p.actor.subject_id, org, (page - 1) * 20)
        rows = decoded(result['rows'])
        # Decode timestamp fields restored from the statement's JSON boundary.
        for row in rows:
            row['expires_at'] = datetime.fromisoformat(row['expires_at'])
        decisions = await tx.fetch('SELECT * FROM l14_quote_decisions WHERE quote_id=ANY($1::uuid[])',
                                   [UUID(row['id']) for row in rows])
    by_id = {str(d['quote_id']): d for d in decisions}
    return {'items': [repair_projection(row, by_id.get(row['id'])) for row in rows],
            'page': page, 'page_size': 20, 'total': result['total']}


@router.get('/{quote_id}')
async def read(quote_id: UUID, request: Request, p=Depends(peers.principal)):
    async with request.app.state.pool.acquire() as tx:
        row = await load(tx, quote_id, 'repair')
        access(row, p)
        decision = await tx.fetchrow('SELECT * FROM l14_quote_decisions WHERE quote_id=$1', quote_id)
    return repair_projection(row, decision)
