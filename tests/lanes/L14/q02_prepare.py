"""Q02 real API setup: native accounts, actual review/publication, contention.

Only the documented one-time local operator bootstrap is administrative. No
approval, fee review, listing, reservation, offer result or payment is SQL-seeded.
"""
import concurrent.futures
import secrets
import struct
import time
import zlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import httpx


def photo():
    width, height = 320, 240
    pixels = bytearray()
    for y in range(height):
        pixels.append(0)
        for x in range(width):
            radius = (x - 160) ** 2 + (y - 120) ** 2
            color = (75, 80, 88) if 3600 < radius < 4600 or (150 < x < 170 and 35 < y < 205) else (230, 232, 235)
            pixels.extend(color)
    def chunk(kind, value):
        return struct.pack('!I', len(value)) + kind + value + struct.pack('!I', zlib.crc32(kind + value) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(bytes(pixels))) + chunk(b'IEND', b'')


def prepare(ports, origin, bootstrap, *, browser_positive=False):
    client = httpx.Client(timeout=12)
    actors = {}
    evidence = {'sample_content': True, 'scope': 'real Identity/Catalog/Pricing/Orders HTTP; no seeded terminal states', 'negative': {}}
    def call(service, method, path, *, actor=None, body=None, expected=200, headers=None, content=None):
        response = client.request(method, f'http://127.0.0.1:{ports[service]}' + path,
            headers={'Origin': origin, 'Idempotency-Key': str(uuid4()),
                **({'Authorization': 'Bearer ' + actors[actor]['token']} if actor else {}), **(headers or {})}, json=body, content=content)
        allowed = [expected] if isinstance(expected, int) else expected
        assert response.status_code in allowed, (service, method, path, response.status_code, response.text)
        return response.json()
    def login(name):
        person = actors[name]
        result = call('identity', 'POST', '/v1/accounts/login', body={'email': person['email'], 'password': person['password']})
        person['token'] = result['access_token']
        return result
    for name in ['operator', 'seller', 'buyer', 'other']:
        email = f'sample-l14-{name}-{uuid4().hex[:10]}@example.test'
        password = 'Sample-2026-' + secrets.token_urlsafe(18) + '!'
        person = call('identity', 'POST', '/v1/accounts/register', body={'email': email, 'password': password, 'display_name': 'Sample ' + name}, expected=201)
        actors[name] = {'email': email, 'password': password, 'id': person['account']['id'], 'token': person['access_token']}
    bootstrap(actors['operator']['email'])
    login('operator')
    application = call('identity', 'POST', '/v1/private-seller/applications', actor='seller', body={
        'identity_name': 'DEMO synthetic sample seller', 'contact': actors['seller']['email'], 'payout_reference': 'DEMO-SAMPLE-RECIPIENT',
        'identity_evidence': 'DEMO: synthetic account identity for isolated offer checks',
        'possession_evidence': 'DEMO: synthetic sample context, not a physical inspection', 'expected_revision': 0})['application']
    assigned = call('identity', 'POST', '/v1/private-reviews', actor='operator', body={'application_id': application['id'],
        'reviewer_id': actors['operator']['id'], 'reason': 'Sample independent review in an isolated validation database'})
    reviewed = call('identity', 'POST', '/v1/private-reviews/' + assigned['id'] + '/verdict', actor='operator', body={
        'revision': assigned['revision'], 'application_revision': application['revision'], 'state': 'approved',
        'reason': 'Approve synthetic DEMO evidence for isolated marketplace validation only'})
    assert reviewed['state'] == 'approved'
    login('seller')
    def quote(actor, listing, purpose, price, *, authoritative=False, revision=None):
        body = {'subject_id': listing['id'], 'subject_revision': revision or listing['revision'], 'purpose': purpose,
            'currency': 'USD', 'price_minor': price, 'schedule_id': 'usd-v2', 'source': 'listing' if authoritative else 'sample'}
        q = call('pricing', 'POST', '/v1/quotes', actor=actor, body=body, expected=201)
        call('pricing', 'POST', '/v1/quotes/' + q['id'] + '/review', actor=actor,
            body={**body, 'quote_revision': q['revision'], 'payable_minor': q['payable_minor']})
        return q
    listings = []
    for index in range(2):
        facts = {'brand': 'Sample', 'model': 'Offer proof ' + str(index + 1), 'reference': 'SAMPLE-CONTENT-ONLY', 'year': 2026,
            'condition': 'Clearly labeled sample content; not a physical watch offered by the platform',
            'component_wear': {'case': 'Synthetic sample condition'}, 'location': 'Beirut (sample)', 'included': [],
            'no_documents': True, 'modified': False, 'modifications': [], 'ownership_confirmed': True,
            'sale_mode': 'fixed_price', 'currency': 'USD', 'price_minor': 10000}
        listing = call('catalog', 'POST', '/v1/seller/listings', actor='seller', body={'facts': facts, 'demo_key': f'DEMO-WATCH-0{index + 1}'}, expected=201)
        call('catalog', 'POST', '/v1/seller/listings/' + listing['id'] + '/media?kind=public_photo&public_safe=true', actor='seller',
            content=photo(), headers={'Content-Type': 'image/png', 'If-Match': str(listing['revision'])}, expected=201)
        listing = call('catalog', 'GET', '/v1/seller/listings/' + listing['id'], actor='seller')
        q = quote('seller', listing, 'purchase', 10000)
        listing = call('catalog', 'POST', '/v1/seller/listings/' + listing['id'] + '/publish', actor='seller',
            headers={'If-Match': str(listing['revision'])}, body={'fee_quote_id': q['id'], 'rules_version': 'usd-v2'})
        assert listing['status'] == 'published' and listing['is_demo'] is True
        listings.append(listing)
    def offer_command(actor, listing, price=9000, **changes):
        q = quote(actor, listing, 'offer', price)
        return {'listing_id': listing['id'], 'listing_revision': listing['revision'], 'amount_minor': price,
            'currency': 'USD', 'schedule_id': 'usd-v2', 'fee_quote_id': q['id'], **changes}
    def offer(actor, listing, price=9000):
        return call('pricing', 'POST', '/v1/offers', actor=actor, body=offer_command(actor, listing, price), expected=201)['offer']
    def observe_payment_notice(order, actor):
        if 'communications' not in ports:
            assert order['state'] == 'awaiting_notification' and order['notified_at'] is None and order['deadline'] is None, order
            evidence['payment_notice'] = {'status': 'withheld', 'reason': 'No Communications producer in the isolated Q02 stack'}
            return order
        limit = time.monotonic() + 60
        while order['state'] == 'awaiting_notification' and time.monotonic() < limit:
            assert order['notified_at'] is None and order['deadline'] is None, order
            time.sleep(0.5)
            order = call('orders', 'GET', '/v1/orders/' + order['id'], actor=actor)['order']
        assert order['state'] == 'awaiting_payment' and order['notified_at'] and order['deadline'], order
        evidence['payment_notice'] = {'status': 'observed'}
        return order
    race, positive = listings
    evidence['negative']['self'] = call('pricing', 'POST', '/v1/offers', actor='seller', body=offer_command('seller', race), expected=409)['error']['code']
    client_expiry = offer_command('buyer', race, expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    evidence['negative']['client_expiry_rejected'] = call('pricing', 'POST', '/v1/offers', actor='buyer', body=client_expiry, expected=422)['error']['code']
    stale = offer_command('buyer', race, listing_revision=race['revision'] - 1)
    evidence['negative']['stale'] = call('pricing', 'POST', '/v1/offers', actor='buyer', body=stale, expected=409)['error']['code']
    a, b = offer('buyer', race), offer('other', race, 9500)
    exact = quote('other', race, 'purchase', 10000, authoritative=True)
    physical = call('orders', 'GET', '/v1/listings/' + race['id'] + '/availability')
    def answer(item):
        return call('pricing', 'POST', '/v1/offers/' + item['id'] + '/answer', actor='seller',
            body={'expected_revision': item['revision'], 'action': 'accept'}, expected=[200, 409])
    def buy_now():
        return call('orders', 'POST', '/v1/exact-reservations', actor='other', body={'watch_id': physical['watch_id'],
            'quote_id': exact['id'], 'expected_revision': physical['revision']})
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = [future.result() for future in [pool.submit(answer, a), pool.submit(answer, b), pool.submit(buy_now)]]
    for item in [a, b]:
        current = call('pricing', 'GET', '/v1/offers/' + item['id'], actor='seller')
        if current['state'] == 'acceptance_pending':
            call('pricing', 'POST', '/v1/offers/' + item['id'] + '/reconcile', actor='seller', body={})
    records = call('orders', 'GET', '/v1/orders', actor='seller')['items']
    winners = [row for row in records if row['watch_id'] == physical['watch_id']]
    assert len(winners) == 1, winners
    winner = observe_payment_notice(winners[0], 'seller')
    final = call('orders', 'GET', '/v1/listings/' + race['id'] + '/availability')
    assert final['status'] == 'reserved'
    evidence['contention'] = {'submitted_commands': 3, 'orders_for_watch': 1, 'order': winner,
        'outcomes': [{'status': value.get('status'), 'code': value.get('code') or value.get('error', {}).get('code')} for value in results]}
    blocked = offer('other', positive)
    call('pricing', 'POST', '/v1/offers/' + blocked['id'] + '/block', actor='seller', body={})
    evidence['negative']['blocked'] = call('pricing', 'POST', '/v1/offers', actor='other', body=offer_command('other', positive), expected=409)['error']['code']
    if not browser_positive:
        current = offer('buyer', positive)
        accepted = answer(current)
        if accepted.get('status') == 'pending':
            accepted = call('pricing', 'POST', '/v1/offers/' + current['id'] + '/reconcile', actor='seller', body={})
        assert accepted['status'] == 'succeeded' and accepted['offer']['state'] == 'accepted', accepted
        order_id = accepted['offer']['order_id']
        actual = call('orders', 'GET', '/v1/orders/' + order_id, actor='buyer')['order']
        actual = observe_payment_notice(actual, 'buyer')
        assert actual['total_minor'] == 9270 and actual['payment_authority'] is False
        evidence['positive_offer'] = {'offer_id': current['id'], 'order': actual, 'state': accepted['offer']['state']}
    evidence['sample_listing_ids'] = [row['id'] for row in listings]
    # Tokens stay in this test process; only synthetic login material is passed
    # transiently to the native browser form, never a financial browser cache.
    browser = {'listing_id': positive['id'], 'buyer_email': actors['buyer']['email'], 'buyer_password': actors['buyer']['password'],
        'seller_email': actors['seller']['email'], 'seller_password': actors['seller']['password']}
    client.close()
    return evidence, browser
