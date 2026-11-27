"""Actual Orders v2.1 transport, real isolated Auction DB, frozen Catalog read.

This explicitly isolates the unrelated publication dependency; it is NOT a
three-service/browser acceptance claim or a runtime fallback. Orders outcomes,
receipt projection, service authentication and Auction recovery are real.
"""
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4
import httpx
import jwt
from bt_bulkheads import DependencyClient
from bt_runtime.app.settings import Settings
from service_app.dependencies import Dependencies
from service_app.main import create_app

ROOT = Path('/proof/.local/edit-connected')


async def main():
    state = json.loads((ROOT / 'db-auction.json').read_text())
    private, public = os.environ['BT_PROOF_PRIVATE_KEY'], os.environ['BT_PROOF_PUBLIC_KEY']
    orders_url = os.environ['BT_PROOF_ORDERS_URL']
    contexts = {}
    def catalog(request):
        row = contexts.get(request.url.path.rsplit('/', 1)[-1])
        return httpx.Response(200, json=row) if row and request.method == 'GET' else httpx.Response(404)
    clients = {name: DependencyClient(name, 'http://127.0.0.1:9', timeout=1.2, concurrency=4) for name in ['identity', 'pricing']}
    clients['catalog'] = DependencyClient('catalog', 'http://catalog-contract-fixture', transport=httpx.MockTransport(catalog))
    clients['orders'] = DependencyClient('orders', orders_url, timeout=1.2, concurrency=4)
    deps = Dependencies(clients, service_key=private)
    app = create_app(Settings(database_url=state['runtime_url'], service_name='auction', service_auth_public_key=public), deps)
    evidence = {'scope': 'actual Orders v2.1 HTTP + real Auction DB/ASGI; Catalog is an explicit frozen publication fixture',
        'sample_content': True, 'orders_contract': 'orders-commitment/v2.1', 'cases': []}
    def auth(subject, audience):
        now = int(time.time())
        return {'Authorization': 'Bearer ' + jwt.encode({'sub': subject, 'type': 'service', 'iss': 'beirut-time-identity',
            'aud': audience, 'iat': now, 'exp': now + 60}, private, algorithm='RS256')}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(base_url=orders_url, timeout=8) as remote, httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://auction-under-test') as local:
            async def call(target, method, path, *, producer='catalog', body=None, key=None, expected=200):
                response = await (remote if target == 'orders' else local).request(method, path,
                    headers={**auth(producer, target), **({'Idempotency-Key': key} if key else {})}, json=body)
                assert response.status_code == expected, (target, method, path, response.status_code, response.text)
                return response.json()
            for index in range(2):
                listing, watch, seller, auction, photo = (uuid4() for _ in range(5))
                facts = {'brand': 'Sample', 'model': 'Recovery fixture', 'reference': 'SAMPLE-CONTENT', 'year': 2026,
                    'condition': 'Sample test content only', 'component_wear': {'case': 'Sample'}, 'location': 'Beirut (sample)',
                    'included': [], 'no_documents': True, 'modified': False, 'modifications': [], 'ownership_confirmed': True,
                    'sale_mode': 'auction', 'currency': 'USD', 'price_minor': 10000}
                contexts[str(listing)] = {'id': str(listing), 'revision': 1, 'physical_watch_id': str(watch), 'seller_id': str(seller),
                    'organization_id': None, 'seller_type': 'private', 'seller_label': 'Sample contract fixture', 'status': 'published',
                    'facts': facts, 'photo_ids': [str(photo)], 'cover_id': str(photo), 'is_demo': True,
                    'registration': {'watch_id': str(watch), 'listing_id': str(listing), 'sale_mode': 'auction', 'revision': 1},
                    'rules_version': 'sample-fixture.v1', 'published_at': '2026-11-05T00:00:00+00:00'}
                registered = await call('orders', 'POST', '/internal/v1/watches/register', key='sample-register:' + str(watch), body={
                    'watch_id': str(watch), 'listing_id': str(listing), 'seller_id': str(seller), 'organization_id': None,
                    'listing_revision': 1, 'sale_mode': 'auction', 'is_demo': True})
                assert registered['status'] == 'succeeded'
                opened = await call('orders', 'POST', '/internal/v2/commitments', producer='auction', key='sample-open:' + str(auction), body={
                    'operation_key': 'sample-open:' + str(auction), 'watch_id': str(watch), 'listing_id': str(listing),
                    'listing_revision': 1, 'expected_revision': 1, 'source_id': str(auction), 'kind': 'auction_open',
                    'reason': 'Sample component context; no bid or payment'})
                assert opened['status'] == 'succeeded' and opened['watch']['revision'] == 2
                # Only unbid sample content is seeded. All physical edits,
                # outcomes, denial receipts and recovery effects use real APIs.
                async with app.state.pool.acquire() as tx:
                    await tx.execute('''INSERT INTO auction_lots(id,listing_id,watch_id,seller_id,currency,opening_minor,
                        increment_bands,starts_at,ends_at,high_value_minor,commitment_id)
                        VALUES($1,$2,$3,$4,'USD',10000,$5::jsonb,clock_timestamp()-interval '1 minute',
                        clock_timestamp()+interval '2 hours',10000000,$6)''', auction, listing, watch, seller,
                        json.dumps([{'from_minor': 0, 'step_minor': 1000}]), str(auction))
                operation = str(uuid4())
                digest = hashlib.sha256(json.dumps({**facts, 'reference': 'SAMPLE-NEXT'}, sort_keys=True,
                    separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
                prepare = {'operation_id': operation, 'listing_id': str(listing), 'watch_id': str(watch),
                    'listing_revision': 1, 'next_revision': 2, 'facts_digest': digest}
                command = {'operation_key': operation, 'watch_id': str(watch), 'listing_id': str(listing),
                    'listing_revision': 1, 'expected_revision': 1 if index == 0 else 2, 'source_id': operation, 'kind': 'edit',
                    'reason': 'Sample retained edit command'}
                if index == 0:
                    # Legacy Catalog captured R1 before Auction open advanced it
                    # to R2. Real Orders must deny without releasing its fence.
                    prepared = await call('auction', 'POST', '/internal/v2/listing-edits/prepare', body=prepare)
                    assert prepared['phase'] == 'prepared'
                    denied = await call('orders', 'POST', '/internal/v2/commitments', body=command, key=operation)
                    assert denied['status'] == 'denied' and denied['code'] == 'stale_revision'
                    proof_path = f'/internal/v2/listing-edit-operations/{operation}?operation_key={operation}'
                    proof = await call('orders', 'GET', proof_path, producer='auction')
                    assert proof['status'] == 'denied' and proof['id'] == denied['id'] and proof['expected_revision'] == 1
                    await call('orders', 'GET', proof_path, expected=403)
                    await call('orders', 'GET', proof_path, producer='pricing', expected=403)
                    await call('orders', 'GET', f'/internal/v2/operations/{operation}', producer='auction', expected=404)
                    await call('orders', 'GET', f'/internal/v2/listing-edit-operations/{uuid4()}?operation_key={operation}', producer='auction', expected=404)
                    path = f'/internal/v3/listing-edits/{operation}'
                    aborted = await call('auction', 'POST', path + '/abort')
                    assert aborted['phase'] == 'aborted' and aborted['code'] == 'orders_denied'
                    assert await call('auction', 'POST', path + '/abort') == aborted
                    assert await call('auction', 'POST', path + '/reconcile') == aborted
                    current = await call('auction', 'GET', '/v2/auctions/' + str(auction))
                    assert current['mode'] == 'bidding' and current['revision'] == 3 and current['listing_revision'] == 1
                    physical = await call('orders', 'GET', '/internal/v2/watches/' + str(watch), producer='auction')
                    assert physical['status'] == 'fenced' and physical['source_id'] == str(auction) and physical['auction_committed'] is False
                    async with app.state.pool.acquire() as tx:
                        assert await tx.fetchval("SELECT count(*) FROM outbox WHERE envelope->>'type'='auction.listing-edit-aborted.v3'") == 1
                        assert await tx.fetchval('SELECT count(*) FROM auction_bids') == 0
                    evidence['cases'].append({'case': 'real durable denial -> confirmed abort/replay exactly once', 'proof': proof, 'outcome': aborted})
                else:
                    prepare.update(orders_operation_key=operation, orders_expected_revision=2, lease_seconds=30)
                    assert (await call('auction', 'POST', '/internal/v3/listing-edits/prepare', body=prepare))['phase'] == 'prepared'
                    path = f'/internal/v3/listing-edits/{operation}'
                    assert (await call('auction', 'POST', path + '/dispatch'))['phase'] == 'dispatched'
                    unknown = await call('auction', 'POST', path + '/abort')
                    assert unknown['status'] == 'pending' and unknown['code'] == 'orders_resolution_unknown'
                    assert (await call('orders', 'POST', '/internal/v2/commitments', body=command, key=operation))['status'] == 'succeeded'
                    held = await call('auction', 'POST', path + '/abort')
                    assert held['status'] == 'pending' and held['code'] == 'orders_edit_succeeded'
                    current = await call('auction', 'GET', '/v2/auctions/' + str(auction))
                    assert current['mode'] == 'listing_edit_pending' and current['revision'] == 2
                    evidence['cases'].append({'case': 'real missing/succeeded receipt stays held', 'unknown': unknown, 'held': held})
    (ROOT / 'evidence.json').write_text(json.dumps(evidence, indent=2))
    print('Actual Orders v2.1 read/denial/producer privacy and Auction abort/replay passed. Catalog was explicitly fixture-scoped; no full story acceptance claimed.')


if __name__ == '__main__':
    asyncio.run(main())
