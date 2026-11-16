"""C09/S02 immutable assessed quotes and explicit, attributable buyer consent."""
import json
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from bt_contracts.pricing.quotes.assessed import IssueQuote, AcceptQuote, DeclineQuote, AssessedScopeLine
from bt_contracts.pricing.quotes.events import AssessedQuoteFact
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts_core.models import EventEnvelope
from bt_runtime.app.db import unit_of_work
from bt_runtime.principal import require_scope
from bt_events import enqueue
from . import peers
from .current import JOB_POLICY, amounts, buyer, decoded, digest, replay, remember, current_time, require_usd
from .security import idempotency


async def current_source(request, kind, snapshot):
    """Version-bound provider seam; missing provider fails closed, never demo pass."""
    if kind == 'brand':
        source = await peers.call(request, 'catalog', 'GET',
            f"/internal/v2/customization-requests/{snapshot['source_id']}?expected_revision={snapshot['source_revision']}", internal=True)
        assessment = await peers.call(request, 'service-operations', 'GET',
            f"/internal/v1/brand-assessments/{snapshot['assessment_id']}/current", internal=True)
        valid = (source.get('id') == snapshot['source_id'] and type(source.get('revision')) is int
                 and source.get('revision') == snapshot['source_revision'] and type(assessment.get('request_revision')) is int
                 and assessment.get('request_id') == source['id']
                 and assessment.get('request_revision') == source['revision']
                 and assessment.get('organization_id') == source.get('brand_id')
                 and assessment.get('status') == 'feasible')
    else:
        assessment = await peers.call(request, 'service-operations', 'GET',
            f"/internal/v1/service-cases/{snapshot['source_id']}/diagnosis", internal=True)
        source = assessment
        valid = (assessment.get('case_id') == snapshot['source_id']
                 and type(assessment.get('case_revision')) is int and assessment.get('case_revision') == snapshot['source_revision']
                 and assessment.get('diagnosis_allowed') is True and assessment.get('status') == 'diagnosed')
    try:
        if (not valid or assessment['id'] != snapshot['assessment_id']
                or type(assessment['revision']) is not int or assessment['revision'] != snapshot['assessment_revision'] or assessment['current'] is not True):
            raise PublicError('source_changed', 'The assessed scope changed. Obtain a new quote and consent.', status=409)
        lines = [AssessedScopeLine.model_validate(line).model_dump(mode='json') for line in assessment['lines']]
        if not 1 <= len(lines) <= 40 or len({line['id'] for line in lines}) != len(lines):
            raise ValueError()
        if str(UUID(assessment['buyer_id'])) != str(UUID(source['buyer_id'])):
            raise PublicError('source_changed', 'The current assessed buyer changed.', status=409)
        result = {'buyer_id': str(UUID(source['buyer_id'])),
                  'organization_id': str(UUID(assessment['organization_id'])),
                  'line_ids': {str(UUID(line_id)) for line_id in assessment['line_ids']},
                  'lines': lines, 'currency': assessment['currency'],
                  'diagnosis': assessment['diagnosis'] if kind == 'repair' else assessment['technical_summary']}
        if not isinstance(result['diagnosis'], str) or not 1 <= len(result['diagnosis']) <= 2000:
            raise ValueError()
        if ({line['id'] for line in lines} != result['line_ids'] or result['currency'] != 'USD'
                or len(assessment['line_ids']) != len(lines)):
            raise ValueError()
    except (KeyError, ValueError, TypeError, ValidationError):
        raise PublicError('dependency_unavailable', 'Current assessed scope cannot be verified.', status=503) from None
    business = await peers.call(request, 'identity', 'GET', f"/v1/businesses/{result['organization_id']}")
    if (business.get('id') != result['organization_id'] or business.get('state') != 'active'
            or business.get('authenticated_business') is not True or business.get('platform_onboarded') is not True
            or (kind == 'brand' and business.get('kind') != 'brand')
            or ('customization' if kind == 'brand' else 'servicing') not in business.get('capabilities', [])):
        raise PublicError('authority_revoked', 'The business no longer has the required current authority.', status=409)
    if kind == 'brand' and source.get('consent_effective') is False:
        raise PublicError('consent_withdrawn', 'Consent is ineffective; accepted economics remain historical.', status=409)
    return result


def project(row, decision=None):
    snapshot = decoded(row['snapshot'])
    state = row['state']
    if state == 'issued' and datetime.now(timezone.utc) >= row['expires_at']:
        state = 'expired_return_held'
    result = {**snapshot, 'state': state, 'decision': None,
              'economics_expires_at': None if state == 'accepted' else row['expires_at'].isoformat()}
    if decision:
        result['decision'] = {'state': decision['decision'], 'actor_id': str(decision['actor_id']),
            'accepted_at': decision['decided_at'].isoformat() if decision['decision'] == 'accepted' else None,
            'decided_at': decision['decided_at'].isoformat(), 'selected_line_ids': decoded(decision['selected_line_ids']),
            'amounts': decoded(decision['amounts']), 'terms_digest': decision['terms_digest'],
            'accepted_fee_lines': decoded(decision['accepted_fee_lines'])}
    return result


def access(row, p):
    if row['buyer_id'] == p.actor.subject_id and p.actor.organization_id is None:
        buyer(p)
    else:
        require_scope(p, 'business.records.read', row['organization_id'])


async def load(tx, quote_id, kind, *, for_update=False):
    row = await tx.fetchrow('SELECT * FROM l14_assessed_quotes WHERE id=$1 AND kind=$2' + (' FOR UPDATE' if for_update else ''), quote_id, kind)
    if not row:
        raise PublicError('not_found', 'Quote not found.', status=404)
    return row


async def event(tx, request, row, action, selection=None):
    data = {key: str(row[key]) if isinstance(row[key], UUID) else row[key] for key in
            ('id', 'revision', 'source_id', 'source_revision', 'buyer_id', 'organization_id', 'state')}
    data['quote_id'] = data.pop('id')
    snapshot = decoded(row['snapshot'])
    data.update(assessment_id=snapshot['assessment_id'], assessment_revision=snapshot['assessment_revision'])
    if selection:
        data.update(selection)
    await enqueue(tx, EventEnvelope(type=f"pricing.{row['kind']}-quote.{action}.v1", source='pricing',
        subject=str(row['id']), request_id=request.state.request_id,
        data=AssessedQuoteFact.model_validate(data).model_dump(mode='json', exclude_none=True)),
        ['pricing-notices-v2', 'accepted-quotes-v1'])


async def decide(kind, quote_id, body, request, p, key, *, accepting):
    buyer(p)
    fingerprint = digest([kind, 'accept' if accepting else 'decline', str(quote_id), body.model_dump(mode='json')])
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
        row = await load(tx, quote_id, kind)
        if row['buyer_id'] != p.actor.subject_id:
            raise AccessDenied('Only the quote buyer decides')
    if prior:
        return prior
    snapshot = decoded(row['snapshot'])
    require_usd(snapshot)
    if snapshot.get('policy', {}).get('revision') != 2:
        raise PublicError('legacy_reconciliation', 'Review a reissued USD job quote; old terms remain unchanged.', status=409)
    source = await current_source(request, kind, snapshot)
    if source['buyer_id'] != str(row['buyer_id']) or source['organization_id'] != str(row['organization_id']):
        raise PublicError('source_changed', 'The current quote parties changed.', status=409)
    selected = sorted(str(value) for value in body.selected_line_ids) if accepting else []
    if accepting and snapshot['assessment_fee_minor'] and not body.accept_assessment_fee:
        raise PublicError('fee_consent_required', 'Explicitly accept the itemized assessment fee.', status=409)
    totals = amounts(snapshot['lines'], selected, snapshot['assessment_fee_minor']) if accepting else {}
    fee_lines = {'assessment': body.accept_assessment_fee, 'return_transport': body.accept_return_fee}
    if (body.quote_revision != row['revision'] or body.terms_digest != snapshot['terms_digest']
            or (accepting and body.payable_minor != totals['payable_minor'])):
        raise PublicError('quote_binding_mismatch', 'Review and explicitly accept the exact current lines, total and terms.', status=409)
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
        if prior:
            return prior
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f"assessed:{kind}:{row['source_id']}")
        row = await load(tx, quote_id, kind, for_update=True)
        now = await tx.fetchval('SELECT clock_timestamp()')
        current_time(row, now)
        if row['state'] != 'issued':
            raise PublicError('quote_not_current', 'Quote expired, changed or was already decided. Review a current quote.', status=409)
        state = 'accepted' if accepting else 'declined_return_held'
        await tx.execute('''INSERT INTO l14_quote_decisions(quote_id,actor_id,decision,selected_line_ids,amounts,terms_digest,decided_at,accepted_fee_lines)
            VALUES($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8::jsonb)''', quote_id, p.actor.subject_id, state,
            json.dumps(selected), json.dumps(totals), body.terms_digest, now, json.dumps(fee_lines))
        row = await tx.fetchrow('UPDATE l14_assessed_quotes SET state=$2 WHERE id=$1 RETURNING *', quote_id, state)
        decision = await tx.fetchrow('SELECT * FROM l14_quote_decisions WHERE quote_id=$1', quote_id)
        await event(tx, request, row, 'accepted' if accepting else 'declined',
            {'selected_line_ids': selected, 'total_minor': totals.get('payable_minor'),
             'currency': snapshot['currency'], 'terms_digest': body.terms_digest})
        return await remember(tx, p, key, fingerprint, {'status': 'succeeded', 'quote': project(row, decision)})


def build_router(kind):
    router = APIRouter(prefix=f'/v1/{kind}-quotes', tags=[kind + ' quotes'])

    @router.get('/context')
    async def context(source_id: UUID, source_revision: int, assessment_id: UUID, assessment_revision: int,
                      request: Request, p=Depends(peers.principal)):
        org = p.actor.organization_id
        if org is None:
            raise AccessDenied('Select the official business')
        require_scope(p, 'business.jobs.write', org)
        binding = {'source_id': str(source_id), 'source_revision': source_revision,
                   'assessment_id': str(assessment_id), 'assessment_revision': assessment_revision}
        source = await current_source(request, kind, binding)
        if source['organization_id'] != str(org):
            raise AccessDenied('Wrong business')
        return {**binding, 'currency': source['currency'], 'lines': source['lines'], 'diagnosis': source['diagnosis']}

    @router.post('', status_code=201)
    async def issue(body: IssueQuote, request: Request, p=Depends(peers.principal), key=Depends(idempotency)):
        org = p.actor.organization_id
        if org is None:
            raise AccessDenied('Select the official business')
        require_scope(p, 'business.jobs.write', org)
        fingerprint = digest([kind, 'issue', body.model_dump(mode='json')])
        async with unit_of_work(request.app.state.pool) as tx:
            prior = await replay(tx, p, key, fingerprint)
        if prior:
            return prior
        snapshot = body.model_dump(mode='json')
        source = await current_source(request, kind, snapshot)
        if source['organization_id'] != str(org) or source['buyer_id'] == str(p.actor.subject_id):
            raise AccessDenied('Wrong assessed business or self quote')
        quoted = {str(line.id): line for line in body.lines}
        if (set(quoted) != source['line_ids'] or body.currency != source['currency']
                or any(quoted[line['id']].mandatory != line['mandatory'] or quoted[line['id']].kind != line['kind']
                       or quoted[line['id']].label != line['label']
                       or quoted[line['id']].part_reference != line.get('part_reference') for line in source['lines'])):
            raise PublicError('scope_mismatch', 'Quote the exact current assessed lines and required scope.', status=409)
        if kind == 'brand' and any(not line.mandatory for line in body.lines):
            raise PublicError('scope_mismatch', 'Brand quotes bind the complete assessed configuration.', status=409)
        if kind == 'brand' and {str(line.id) for line in body.lines} != source['line_ids']:
            raise PublicError('scope_mismatch', 'Quote the complete assessed configuration.', status=409)
        async with unit_of_work(request.app.state.pool) as tx:
            prior = await replay(tx, p, key, fingerprint)
            if prior:
                return prior
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', f'assessed:{kind}:{body.source_id}')
            now = await tx.fetchval('SELECT clock_timestamp()')
            expires_at = min(body.expires_at, now + timedelta(minutes=15)) if body.expires_at else now + timedelta(minutes=15)
            if expires_at <= now:
                raise PublicError('invalid_expiry', 'Review an unexpired fifteen-minute quote.', status=409)
            snapshot['expires_at'] = expires_at.isoformat()
            revision = 1 + (await tx.fetchval('SELECT max(revision) FROM l14_assessed_quotes WHERE kind=$1 AND source_id=$2', kind, body.source_id) or 0)
            quote_id = uuid4()
            snapshot.update(id=str(quote_id), revision=revision, kind=kind, buyer_id=source['buyer_id'],
                organization_id=str(org), author_id=str(p.actor.subject_id), diagnosis=source['diagnosis'], policy=JOB_POLICY, created_at=now.isoformat())
            snapshot['terms_digest'] = digest(snapshot)
            snapshot['full_total'] = amounts(snapshot['lines'], [str(line.id) for line in body.lines], body.assessment_fee_minor)
            await tx.execute("UPDATE l14_assessed_quotes SET state='superseded' WHERE kind=$1 AND source_id=$2 AND state IN ('issued','accepted')", kind, body.source_id)
            row = await tx.fetchrow('''INSERT INTO l14_assessed_quotes(id,kind,source_id,source_revision,buyer_id,organization_id,author_id,
                revision,snapshot,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10) RETURNING *''', quote_id, kind,
                body.source_id, body.source_revision, UUID(source['buyer_id']), org, p.actor.subject_id,
                revision, json.dumps(snapshot), expires_at)
            await event(tx, request, row, 'issued')
            return await remember(tx, p, key, fingerprint, {'status': 'succeeded', 'quote': project(row)})

    @router.get('')
    async def listing(request: Request, p=Depends(peers.principal)):
        org = p.actor.organization_id
        if org:
            require_scope(p, 'business.records.read', org)
        else:
            buyer(p)
        async with request.app.state.pool.acquire() as tx:
            rows = await tx.fetch('''SELECT * FROM l14_assessed_quotes WHERE kind=$1 AND
                (($3::uuid IS NULL AND buyer_id=$2) OR organization_id=$3) AND snapshot->>'currency'='USD' ORDER BY created_at DESC,id DESC LIMIT 50''',
                kind, p.actor.subject_id, org)
            decisions = await tx.fetch('SELECT * FROM l14_quote_decisions WHERE quote_id=ANY($1::uuid[])', [row['id'] for row in rows])
        by_id = {d['quote_id']: d for d in decisions}
        return {'items': [project(row, by_id.get(row['id'])) for row in rows]}

    @router.get('/{quote_id}')
    async def read(quote_id: UUID, request: Request, p=Depends(peers.principal)):
        async with request.app.state.pool.acquire() as tx:
            row = await load(tx, quote_id, kind)
            access(row, p)
            decision = await tx.fetchrow('SELECT * FROM l14_quote_decisions WHERE quote_id=$1', quote_id)
        return project(row, decision)

    @router.post('/{quote_id}/accept')
    async def accept(quote_id: UUID, body: AcceptQuote, request: Request, p=Depends(peers.principal), key=Depends(idempotency)):
        return await decide(kind, quote_id, body, request, p, key, accepting=True)

    @router.post('/{quote_id}/decline')
    async def decline(quote_id: UUID, body: DeclineQuote, request: Request, p=Depends(peers.principal), key=Depends(idempotency)):
        return await decide(kind, quote_id, body, request, p, key, accepting=False)

    return router
