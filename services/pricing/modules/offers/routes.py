"""Q02: Pricing owns agreement; Orders alone owns the physical reservation."""
import json
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, Request, HTTPException
from bt_contracts.pricing.offers.models import MakeOffer, AnswerOffer
from bt_contracts.pricing.offers.events import OfferFact
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work
from service_app import peers
from service_app.current import buyer, decoded, digest, replay, remember
from service_app.security import idempotency

router = APIRouter(prefix='/v1/offers', tags=['offers'])


def seller_scope(row):
    return str(row['seller_organization_id'] or row['seller_id'])


def party(row, p):
    if row['buyer_id'] == p.actor.subject_id and p.actor.organization_id is None:
        buyer(p)
        return 'buyer'
    peers.seller(p, row['seller_id'], row['seller_organization_id'])
    return 'seller'


def project(row):
    state = row['state']
    if state == 'open' and datetime.now(timezone.utc) >= row['expires_at']:
        state = 'expired'
    remote = decoded(row['orders_result']) if row['orders_result'] else None
    return {'id': str(row['id']), 'listing_id': str(row['listing_id']), 'listing_revision': row['listing_revision'],
            'revision': row['revision'], 'buyer_id': str(row['buyer_id']), 'seller_id': str(row['seller_id']),
            'organization_id': str(row['seller_organization_id']) if row['seller_organization_id'] else None,
            'state': state, 'expires_at': row['expires_at'].isoformat(), 'quote': decoded(row['snapshot']),
            'order_id': str(remote['order']['id']) if remote and (remote.get('order') or {}).get('id') else None}


async def load(tx, offer_id, *, for_update=False):
    row = await tx.fetchrow('SELECT * FROM l14_offers WHERE id=$1' + (' FOR UPDATE' if for_update else ''), offer_id)
    if not row:
        raise PublicError('not_found', 'Offer not found.', status=404)
    return row


async def blocked(tx, row):
    if await tx.fetchval('SELECT EXISTS(SELECT 1 FROM l14_offer_blocks WHERE seller_scope=$1 AND buyer_id=$2)',
                          seller_scope(row), row['buyer_id']):
        raise PublicError('offer_blocked', 'Offers between these parties are blocked.', status=409)


async def notice(tx, request, row, kind):
    # This distinct destination is enabled only with the v2 subscribed receiver;
    # legacy quote relay cannot accidentally send unsupported new event types.
    await enqueue(tx, EventEnvelope(type='pricing.offer.' + kind + '.v1', source='pricing',
        subject=str(row['id']), request_id=request.state.request_id,
        data=OfferFact(offer_id=row['id'], listing_id=row['listing_id'], buyer_id=row['buyer_id'],
            seller_id=row['seller_id'], seller_organization_id=row['seller_organization_id'],
            revision=row['revision'], state=row['state']).model_dump(mode='json')), ['pricing-notices-v2'])


@router.post('', status_code=201)
async def make(body: MakeOffer, request: Request, p=Depends(peers.principal), key=Depends(idempotency)):
    buyer(p)
    fingerprint = digest(['offer', body.model_dump(mode='json')])
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
    if prior:
        return prior
    source = await peers.listing(request, body.listing_id, body.listing_revision)
    if source['seller_id'] == str(p.actor.subject_id) or (source['organization_id'] and
            UUID(source['organization_id']) in p.organizations):
        raise PublicError('self_offer', 'A seller or business member cannot make this offer.', status=409)
    if source['facts']['currency'] != body.currency:
        raise PublicError('currency_mismatch', 'Use the listing currency.', status=409)
    availability = await peers.call(request, 'orders', 'GET', f"/internal/v2/watches/{source['physical_watch_id']}", internal=True)
    if availability.get('status') != 'available' or availability.get('listing_revision') != body.listing_revision:
        raise PublicError('watch_committed', 'This current watch is unavailable for offers.', status=409)
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
        if prior:
            return prior
        now = await tx.fetchval('SELECT clock_timestamp()')
        if not now < body.expires_at <= now + timedelta(days=7):
            raise PublicError('invalid_expiry', 'Offer expiry must be within seven days.', status=409)
        q = await tx.fetchrow('SELECT * FROM l07_quotes WHERE id=$1 AND owner_id=$2', body.fee_quote_id, p.actor.subject_id)
        if q is None:
            raise PublicError('fee_review_required', 'Review the exact offer fees first.', status=409)
        quote = decoded(q['snapshot'])
        if (not q['reviewed_at'] or q['expires_at'] <= now or quote['purpose'] != 'offer'
                or quote['subject_id'] != str(body.listing_id) or quote['subject_revision'] != body.listing_revision
                or quote['price_minor'] != body.amount_minor or quote['currency'] != body.currency):
            raise PublicError('fee_review_required', 'Review the exact current offer and fees first.', status=409)
        row_scope = {'seller_id': source['seller_id'], 'seller_organization_id': source['organization_id'], 'buyer_id': p.actor.subject_id}
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'offer-listing:' + str(body.listing_id))
        await blocked(tx, row_scope)
        if await tx.fetchval("SELECT EXISTS(SELECT 1 FROM l14_offers WHERE listing_id=$1 AND state='accepted')", body.listing_id):
            raise PublicError('watch_committed', 'This watch already has an accepted offer.', status=409)
        if await tx.fetchval('SELECT EXISTS(SELECT 1 FROM l14_offers WHERE quote_id=$1)', body.fee_quote_id):
            raise PublicError('offer_exists', 'This exact offer quote has already been sent.', status=409)
        row = await tx.fetchrow('''INSERT INTO l14_offers(id,listing_id,listing_revision,watch_id,buyer_id,seller_id,
            seller_organization_id,quote_id,snapshot,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10) RETURNING *''',
            uuid4(), body.listing_id, body.listing_revision, UUID(source['physical_watch_id']), p.actor.subject_id,
            UUID(source['seller_id']), UUID(source['organization_id']) if source['organization_id'] else None,
            body.fee_quote_id, json.dumps(quote), body.expires_at)
        await notice(tx, request, row, 'made')
        return await remember(tx, p, key, fingerprint, {'status': 'succeeded', 'offer': project(row)})


@router.get('')
async def listing(request: Request, p=Depends(peers.principal)):
    org = p.actor.organization_id
    if org:
        from bt_runtime.principal import require_scope
        require_scope(p, 'identity.listings.publish', org)
    async with request.app.state.pool.acquire() as tx:
        rows = await tx.fetch('''SELECT * FROM l14_offers WHERE
            ($2::uuid IS NULL AND (buyer_id=$1 OR (seller_id=$1 AND seller_organization_id IS NULL)))
            OR ($2::uuid IS NOT NULL AND seller_organization_id=$2) ORDER BY created_at DESC,id DESC LIMIT 50''',
            p.actor.subject_id, org)
    for row in rows:
        party(row, p)
    return {'items': [project(row) for row in rows]}


@router.get('/{offer_id}')
async def read(offer_id: UUID, request: Request, p=Depends(peers.principal)):
    async with request.app.state.pool.acquire() as tx:
        row = await load(tx, offer_id)
        side = party(row, p)
    return {**project(row), 'party': side}


async def reconcile(request, offer_id, p):
    async with request.app.state.pool.acquire() as tx:
        row = await load(tx, offer_id)
        if party(row, p) != 'seller':
            raise AccessDenied('Only actual seller reconciles acceptance')
    return await reconcile_intent(request, offer_id)


async def reconcile_intent(request, offer_id):
    # Only called after current-party authorization above, or by the leased
    # worker for an already authorized, immutable durable acceptance intent.
    async with request.app.state.pool.acquire() as tx:
        row = await load(tx, offer_id)
    if row['state'] != 'acceptance_pending':
        return {'status': 'succeeded' if row['state'] == 'accepted' else 'denied', 'offer': project(row)}
    command = decoded(row['orders_command'])
    try:
        remote = await peers.call(request, 'orders', 'GET', '/internal/v2/operations/' + command['operation_key'],
                                  internal=True, missing=True)
        if remote is None:
            # A missing operation is not release. Retry precisely the retained
            # command with precisely the same remote identity.
            remote = await peers.call(request, 'orders', 'POST', '/internal/v2/allocations', internal=True,
                headers={'Idempotency-Key': command['operation_key']}, json=command)
    except (PublicError, AccessDenied, HTTPException):
        # After intent, an HTTP error (including auth/configuration or a lost
        # conflict body) is NOT a durable denied operation. Keep it reconcilable.
        return {'status': 'pending', 'code': 'reservation_unknown', 'offer': project(row)}
    if remote.get('status') not in ('succeeded', 'denied'):
        return {'status': 'pending', 'code': 'reservation_unknown', 'offer': project(row)}
    if remote['status'] == 'succeeded':
        try:
            UUID(remote['order']['id'])
        except (KeyError, TypeError, ValueError):
            return {'status': 'pending', 'code': 'reservation_unknown', 'offer': project(row)}
    async with unit_of_work(request.app.state.pool, lock_key='offer-listing:' + str(row['listing_id'])) as tx:
        row = await load(tx, offer_id)
        if row['state'] == 'acceptance_pending':
            state = 'accepted' if remote['status'] == 'succeeded' else 'lost'
            row = await tx.fetchrow('UPDATE l14_offers SET state=$2,orders_result=$3::jsonb,revision=revision+1 WHERE id=$1 RETURNING *',
                                     offer_id, state, json.dumps(remote))
            await notice(tx, request, row, state)
            if state == 'accepted':
                others = await tx.fetch("UPDATE l14_offers SET state='closed',revision=revision+1 WHERE listing_id=$1 AND id<>$2 AND state='open' RETURNING *",
                                         row['listing_id'], offer_id)
                for other in others:
                    await notice(tx, request, other, 'closed')
            result = {'status': remote['status'], 'offer': project(row)}
            await tx.execute("UPDATE l14_pricing_operations SET result=result || $2::jsonb WHERE id=$1",
                             row['acceptance_operation_id'], json.dumps(result))
        return {'status': 'succeeded' if row['state'] == 'accepted' else 'denied', 'offer': project(row)}


@router.post('/{offer_id}/answer')
async def answer(offer_id: UUID, body: AnswerOffer, request: Request, p=Depends(peers.principal), key=Depends(idempotency)):
    fingerprint = digest(['answer', str(offer_id), body.model_dump(mode='json')])
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
        before = await load(tx, offer_id)
        if party(before, p) != 'seller':
            raise AccessDenied('Only the actual seller answers')
    if prior:
        if prior['status'] == 'pending':
            await reconcile(request, offer_id, p)
            async with request.app.state.pool.acquire() as tx:
                op = await tx.fetchrow('SELECT result FROM l14_pricing_operations WHERE actor_id=$1 AND operation_key=$2', p.actor.subject_id, key)
            return decoded(op['result'])
        return prior
    await peers.listing(request, before['listing_id'], before['listing_revision'])
    remote = None
    if body.action == 'accept':
        remote = await peers.call(request, 'orders', 'GET', f"/internal/v2/watches/{before['watch_id']}", internal=True)
        if remote.get('watch_id') != str(before['watch_id']) or remote.get('listing_id') != str(before['listing_id']):
            raise PublicError('dependency_unavailable', 'The watch commitment cannot be verified.', status=503)
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
        if prior:
            return prior
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'offer-listing:' + str(before['listing_id']))
        row = await load(tx, offer_id, for_update=True)
        party(row, p)
        await blocked(tx, row)
        now = await tx.fetchval('SELECT clock_timestamp()')
        if row['state'] != 'open' or row['revision'] != body.expected_revision or row['expires_at'] <= now:
            raise PublicError('offer_not_current', 'Reload the current unexpired offer.', status=409)
        if body.action == 'reject':
            row = await tx.fetchrow("UPDATE l14_offers SET state='rejected',revision=revision+1 WHERE id=$1 RETURNING *", offer_id)
            await notice(tx, request, row, 'rejected')
            return await remember(tx, p, key, fingerprint, {'status': 'succeeded', 'offer': project(row)})
        quote = decoded(row['snapshot'])
        if datetime.fromisoformat(quote['expires_at']) <= now:
            raise PublicError('quote_expired', 'The buyer must review a fresh offer and fees.', status=409)
        command = {'operation_key': 'offer:' + str(offer_id), 'watch_id': str(row['watch_id']),
                   'listing_id': str(row['listing_id']), 'listing_revision': row['listing_revision'],
                   'expected_revision': remote['revision'], 'source_id': str(offer_id), 'kind': 'offer',
                   'buyer_id': str(row['buyer_id']), 'quote_id': str(row['quote_id']), 'quote_revision': quote['revision'],
                   'currency': quote['currency'], 'total_minor': quote['payable_minor']}
        outcome = await remember(tx, p, key, fingerprint, {'status': 'pending', 'offer': project(row)})
        row = await tx.fetchrow("""UPDATE l14_offers SET state='acceptance_pending',accepted_by=$2,
            acceptance_operation_id=$3,orders_command=$4::jsonb,revision=revision+1 WHERE id=$1 RETURNING *""",
            offer_id, p.actor.subject_id, UUID(outcome['operation_id']), json.dumps(command))
        await tx.execute('UPDATE l14_pricing_operations SET result=$2::jsonb WHERE id=$1', UUID(outcome['operation_id']),
                         json.dumps({**outcome, 'offer': project(row)}))
    await reconcile(request, offer_id, p)
    async with request.app.state.pool.acquire() as tx:
        result = await tx.fetchval('SELECT result FROM l14_pricing_operations WHERE id=$1', UUID(outcome['operation_id']))
    return decoded(result)


@router.post('/{offer_id}/reconcile')
async def recover(offer_id: UUID, request: Request, p=Depends(peers.principal)):
    return await reconcile(request, offer_id, p)


@router.post('/{offer_id}/block')
async def block(offer_id: UUID, request: Request, p=Depends(peers.principal), key=Depends(idempotency)):
    fingerprint = digest(['block', str(offer_id)])
    async with unit_of_work(request.app.state.pool) as tx:
        prior = await replay(tx, p, key, fingerprint)
        if prior:
            return prior
        row = await load(tx, offer_id)
        side = party(row, p)
        await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'offer-listing:' + str(row['listing_id']))
        scope = str(p.actor.subject_id) if side == 'buyer' else seller_scope(row)
        await tx.execute('INSERT INTO l14_offer_blocks(seller_scope,buyer_id,blocker_scope) VALUES($1,$2,$3) ON CONFLICT DO NOTHING',
                         seller_scope(row), row['buyer_id'], scope)
        return await remember(tx, p, key, fingerprint, {'status': 'succeeded', 'code': 'offers_blocked'})
