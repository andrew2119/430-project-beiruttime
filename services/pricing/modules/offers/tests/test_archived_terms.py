"""Legacy sent terms stay available for reconciliation but never drive a new allocation."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import asyncpg
import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from bt_contracts.pricing.offers.models import AnswerOffer, LegacyMakeOffer, MakeOffer
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.principal import CurrentPrincipal
from modules.offers import routes, workers
from modules.quotes import current_routes, current_workers

MODULES = Path(__file__).resolve().parents[2]


@pytest.mark.asyncio
@pytest.mark.parametrize('database_access', ['core-only'], indirect=True)
async def test_offer_archive_cutover_preserves_rows_keys_and_fences(database_owner_url, database_url, monkeypatch):
    buyer, seller = uuid4(), uuid4()
    buyer_scope = CurrentPrincipal(actor={'subject_id': buyer, 'session_id': 'test'}, roles=['buyer'])
    seller_scope = CurrentPrincipal(actor={'subject_id': seller, 'session_id': 'test'},
                                    roles=['private_seller'], permissions=['identity.listings.publish'])
    now = datetime.now(timezone.utc)
    conn = await asyncpg.connect(database_owner_url)

    async def seed(currency, schedule, state, *, revision, expires_at, operation_key, quote_only=False, quote_expiry=None):
        quote_id, offer_id, listing_id, watch_id = uuid4(), uuid4(), uuid4(), uuid4()
        snapshot = {'id': str(quote_id), 'owner_id': str(buyer), 'subject_id': str(listing_id),
                    'subject_revision': 1, 'currency': currency, 'schedule_id': schedule, 'purpose': 'offer',
                    'price_minor': 500000, 'buyer_fee_minor': 15000, 'seller_commission_minor': 25000,
                    'seller_net_minor': 475000, 'shipping_minor': 0, 'tax_minor': 0, 'payable_minor': 515000,
                    'sample': True, 'revision': 1, 'minor_unit_exponent': 2,
                    'policy': {'revision': revision, 'buyer_fee_bps': 300, 'seller_commission_bps': 500}}
        await conn.execute('''INSERT INTO l07_quotes (id,owner_id,idempotency_key,request_hash,snapshot,created_at,expires_at,reviewed_at)
            VALUES ($1,$2,$3,'proof',$4::jsonb,$5,$6,$5)''', quote_id, buyer, 'quote-' + str(quote_id),
            json.dumps(snapshot), now - timedelta(minutes=1), quote_expiry or now + timedelta(minutes=15))
        pending = state == 'acceptance_pending'
        command = {'operation_key': 'offer:' + str(offer_id), 'watch_id': str(watch_id), 'quote_id': str(quote_id),
                   'currency': currency, 'total_minor': 515000} if pending else None
        stored_offer = {'id': str(offer_id), 'state': 'open', 'quote': snapshot}
        result = {'status': 'succeeded', 'offer': stored_offer}
        body = dict(listing_id=listing_id, listing_revision=1, amount_minor=500000, currency=currency,
                    schedule_id=schedule, fee_quote_id=quote_id)
        request_body = LegacyMakeOffer(**body, expires_at=expires_at) if schedule == 'sample-v1' else MakeOffer(**body)
        if quote_only:
            return request_body, watch_id
        await conn.execute('''INSERT INTO l14_pricing_operations VALUES($1,$2,NULL,$3,$4,$5::jsonb)''',
                           uuid4(), buyer, operation_key, routes.digest(['offer', request_body.model_dump(mode='json')]),
                           json.dumps(result))
        acceptance_id = None
        if pending:
            acceptance_id = uuid4()
            accepted = AnswerOffer(expected_revision=1, action='accept')
            receipt = {'operation_id': str(acceptance_id), 'status': 'pending', 'offer': {**stored_offer, 'state': state}}
            await conn.execute('''INSERT INTO l14_pricing_operations VALUES($1,$2,NULL,'retry-answer',$3,$4::jsonb)''',
                               acceptance_id, seller, routes.digest(['answer', str(offer_id), accepted.model_dump(mode='json')]),
                               json.dumps(receipt))
        await conn.execute('''INSERT INTO l14_offers
            (id,listing_id,listing_revision,watch_id,buyer_id,seller_id,quote_id,snapshot,state,expires_at,
             orders_command,accepted_at,accepted_revision,availability_check_after,acceptance_operation_id)
            VALUES ($1,$2,1,$3,$4,$5,$6,$7::jsonb,$8,$9,$10::jsonb,$11,$12,$13,$14)''',
            offer_id, listing_id, watch_id, buyer, seller, quote_id, json.dumps(snapshot), state, expires_at,
            json.dumps(command) if pending else None, now if pending else None, 2 if pending else None,
            (now + timedelta(hours=1)) if schedule == 'usd-v2' else now, acceptance_id)
        return offer_id, request_body, result

    try:
        migrations = sorted((MODULES / 'quotes/migrations').glob('*.sql'))
        for migration in migrations[:-1]:
            await conn.execute(migration.read_text())
        for name in ('quotes/current-state', 'offers'):
            for migration in sorted((MODULES / name / 'migrations').glob('*.sql')):
                await conn.execute(migration.read_text())
        legacy_open, open_body, _ = await seed('USD', 'sample-v1', 'open', revision=1,
                                               expires_at=now + timedelta(hours=1), operation_key='old-open')
        legacy_pending, pending_body, _ = await seed('USD', 'sample-v1', 'acceptance_pending', revision=1,
                                                    expires_at=now + timedelta(hours=1), operation_key='old-pending')
        legacy_lbp, lbp_body, _ = await seed('LBP', 'sample-v1', 'open', revision=1,
                                      expires_at=now - timedelta(hours=1), operation_key='old-lbp-quote')
        await conn.execute(migrations[-1].read_text())
        current, current_body, current_receipt = await seed('USD', 'usd-v2', 'open', revision=2,
                                                           expires_at=now + timedelta(hours=1), operation_key='current-offer')
        current_create, create_watch = await seed('USD', 'usd-v2', 'open', revision=2,
                                                  expires_at=now + timedelta(hours=1), operation_key='unused', quote_only=True)
        expiry = await conn.fetchval('SELECT clock_timestamp()')
        expired_create, expired_watch = await seed('USD', 'usd-v2', 'open', revision=2,
                                                  expires_at=now + timedelta(hours=1), operation_key='expired',
                                                  quote_only=True, quote_expiry=expiry)
        retained_rows = await conn.fetch('SELECT * FROM l14_offers ORDER BY id')
        retained_ops = await conn.fetch('SELECT * FROM l14_pricing_operations ORDER BY id')
        async with asyncpg.create_pool(database_url, min_size=1, max_size=1) as pool:
            app = FastAPI()
            app.include_router(routes.router)
            app.state.pool = pool
            request = SimpleNamespace(app=app, state=SimpleNamespace(request_id=str(uuid4())))
            calls = []

            async def principal(req: Request):
                if req.headers.get('X-Test-Scope') == 'other':
                    return CurrentPrincipal(actor={'subject_id': uuid4(), 'session_id': 'test'}, roles=['buyer'])
                if req.headers.get('X-Test-Scope') == 'business':
                    return CurrentPrincipal(actor={'subject_id': buyer, 'session_id': 'test', 'organization_id': uuid4()}, roles=['buyer'])
                req.state.request_id = str(uuid4())
                return buyer_scope

            app.dependency_overrides[routes.peers.principal] = principal

            @app.exception_handler(PublicError)
            async def public_error(_, error):
                return JSONResponse({'error': {'code': error.code}}, status_code=error.status)

            @app.exception_handler(AccessDenied)
            async def access_denied(_, error):
                return JSONResponse({'error': {'code': 'forbidden'}}, status_code=403)

            async def remote(*args, **kwargs):
                calls.append((args, kwargs))
                pytest.fail('No new Orders or Catalog call is allowed for a legacy retry')

            monkeypatch.setattr(routes.peers, 'call', remote)
            monkeypatch.setattr(routes.peers, 'listing', remote)
            assert [x['id'] for x in (await routes.listing(request, buyer_scope))['items']] == [str(current)]
            assert (await routes.read(current, request, buyer_scope))['state'] == 'open'
            assert await routes.make(current_body, request, buyer_scope, 'current-offer') == current_receipt
            assert await current_routes.operation('current-offer', request, buyer_scope) == current_receipt
            for offer_id, key, code in (
                (legacy_open, 'old-open', 'fee_review_required'),
                (legacy_pending, 'old-pending', 'legacy_reconciliation'),
            ):
                for endpoint, args in (
                    (routes.read, (offer_id, request, buyer_scope)),
                    (routes.answer, (offer_id, AnswerOffer(expected_revision=1, action='accept'), request, seller_scope, 'retry-answer')),
                    (current_routes.operation, (key, request, buyer_scope)),
                    (routes.recover, (offer_id, request, seller_scope)),
                ):
                    with pytest.raises(PublicError, match=code) as error:
                        await endpoint(*args)
                    assert error.value.status == 409
            with pytest.raises(PublicError, match='fee_review_required'):
                await routes.read(legacy_lbp, request, buyer_scope)
            with pytest.raises(PublicError, match='legacy_reconciliation'):
                await routes.reconcile_intent(request, legacy_pending)
            with pytest.raises(PublicError, match='legacy_reconciliation'):
                await current_routes.operation('retry-answer', request, seller_scope)
            assert await workers.tick(app) == 0
            assert await current_workers.tick(app) == 0
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://proof') as client:
                for key, legacy, code, scope, status in (
                    ('old-open', open_body, 'fee_review_required', 'buyer', 409),
                    ('old-pending', pending_body, 'legacy_reconciliation', 'buyer', 409),
                    ('old-lbp-quote', lbp_body, 'fee_review_required', 'buyer', 409),
                    ('no-receipt', pending_body, 'fee_review_required', 'buyer', 409),
                    ('old-pending', pending_body, 'fee_review_required', 'other', 409),
                    ('old-pending', pending_body, 'forbidden', 'business', 403),
                    ('old-pending', pending_body.model_copy(update={'amount_minor': 500001}), 'idempotency_conflict', 'buyer', 409),
                ):
                    response = await client.post('/v1/offers', json=legacy.model_dump(mode='json'),
                                                 headers={'Idempotency-Key': key, 'X-Test-Scope': scope})
                    assert response.status_code == status and response.json()['error']['code'] == code, response.text
            assert calls == []
            assert await conn.fetch('SELECT * FROM l14_offers ORDER BY id') == retained_rows
            assert await conn.fetch('SELECT * FROM l14_pricing_operations ORDER BY id') == retained_ops

            watch_by_listing = {str(current_create.listing_id): str(create_watch), str(expired_create.listing_id): str(expired_watch)}

            async def listing_for_create(_, listing_id, revision):
                return {'seller_id': str(seller), 'organization_id': None, 'facts': {'currency': 'USD'},
                        'physical_watch_id': watch_by_listing[str(listing_id)]}

            async def availability_only(_, service, method, path, **kwargs):
                assert service == 'orders' and method == 'GET' and path.startswith('/internal/v2/watches/')
                watch_id = path.rsplit('/', 1)[-1]
                listing_id = next(id for id, known_watch in watch_by_listing.items() if known_watch == watch_id)
                return {'status': 'available', 'watch_id': watch_id, 'listing_id': listing_id, 'listing_revision': 1}

            monkeypatch.setattr(routes.peers, 'listing', listing_for_create)
            monkeypatch.setattr(routes.peers, 'call', availability_only)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://proof') as client:
                expired = await client.post('/v1/offers', json=expired_create.model_dump(mode='json'),
                                            headers={'Idempotency-Key': 'server-expired'})
                assert expired.status_code == 409 and expired.json()['error']['code'] == 'fee_review_required', expired.text
                assert await conn.fetch('SELECT * FROM l14_offers ORDER BY id') == retained_rows
                assert await conn.fetch('SELECT * FROM l14_pricing_operations ORDER BY id') == retained_ops
                created = await client.post('/v1/offers', json=current_create.model_dump(mode='json'),
                                            headers={'Idempotency-Key': 'new-current'})
                assert created.status_code == 201 and created.json()['status'] == 'succeeded', created.text
                assert created.json()['offer']['quote']['schedule_id'] == 'usd-v2'
            current_row = next(row for row in retained_rows if row['id'] == current)
            posted = []

            async def current_orders(_, service, method, path, **kwargs):
                assert service == 'orders'
                if method == 'GET' and path.startswith('/internal/v2/watches/'):
                    return {'watch_id': str(current_row['watch_id']), 'listing_id': str(current_row['listing_id']),
                            'revision': 1, 'status': 'available'}
                if method == 'GET' and path == '/internal/v2/operations/offer:' + str(current):
                    return None
                assert method == 'POST' and path == '/internal/v2/allocations'
                posted.append(kwargs['json'])
                order_id = str(uuid4())
                return {'id': str(uuid4()), 'request_id': 'orders-archive-test', 'status': 'succeeded',
                        'resource_id': order_id, 'order': {**kwargs['json'], 'id': order_id}}

            async def current_listing(*_):
                return {}

            monkeypatch.setattr(routes.peers, 'call', current_orders)
            monkeypatch.setattr(routes.peers, 'listing', current_listing)
            accepted = await routes.answer(current, AnswerOffer(expected_revision=1, action='accept'),
                                           request, seller_scope, 'answer-current')
            assert accepted['status'] == 'succeeded' and accepted['offer']['state'] == 'accepted'
            assert len(posted) == 1 and posted[0]['currency'] == 'USD' and posted[0]['total_minor'] == 515000
            assert await conn.fetch('SELECT * FROM l14_offers WHERE id=ANY($1::uuid[]) ORDER BY id',
                                    [legacy_open, legacy_pending, legacy_lbp]) == [
                row for row in retained_rows if row['id'] != current]
    finally:
        await conn.close()
