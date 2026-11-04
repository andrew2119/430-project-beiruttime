"""Durable local Inbox bridge, independent of optional email/push preferences."""
import asyncio
import os
import time
from uuid import uuid4
import jwt
from bt_bulkheads import DependencyClient, Unavailable
from .routes import dto


async def bridge(app, stop):
    app.state.bid_notice_clients = {name: DependencyClient(name, os.environ.get(
        f'{name.upper()}_URL', f'http://{name}:8000'), timeout=1.2, concurrency=4)
        for name in ('identity', 'auction')}
    inbox = DependencyClient('inbox', os.environ.get('COMMUNICATIONS_URL', 'http://communications:8000'),
        timeout=1.2, concurrency=1)
    key = os.environ.get('BT_SERVICE_AUTH_PRIVATE_KEY', '')
    try:
        if not key:
            await stop.wait()
            return
        while not stop.is_set():
            lease = uuid4()
            async with app.state.pool.acquire() as tx:
                rows = await tx.fetch('''WITH due AS (SELECT id FROM bid_notices WHERE delivered_at IS NULL
                    AND available_at<=now() AND (leased_until IS NULL OR leased_until<now())
                    ORDER BY available_at,id FOR UPDATE SKIP LOCKED LIMIT 8)
                    UPDATE bid_notices n SET lease_token=$1,leased_until=now()+interval '30 seconds',
                    attempts=attempts+1 FROM due WHERE n.id=due.id RETURNING n.*''', lease)
            for row in rows:
                notice = dto(row)
                now = int(time.time())
                token = jwt.encode({'sub': 'communications', 'type': 'service',
                    'iss': app.state.settings.auth_issuer, 'aud': 'communications',
                    'iat': now, 'exp': now + 60}, key, algorithm='RS256')
                body = {'id': notice['id'], 'recipient_id': str(row['recipient_id']), 'kind': notice['kind'],
                    'resource_type': 'auction', 'resource_id': notice['auction_id'], 'href': notice['href'],
                    'created_at': notice['created_at'], 'data': {k: notice[k] for k in
                        ('current_minor', 'currency', 'ends_at', 'sequence')}}
                result = await inbox.request('POST', '/internal/v1/notices', json=body,
                    headers={'Authorization': 'Bearer ' + token, 'Idempotency-Key': notice['id']})
                ok = not isinstance(result, Unavailable) and 200 <= result.status_code < 300
                async with app.state.pool.acquire() as tx:
                    if ok:
                        await tx.execute('''UPDATE bid_notices SET delivered_at=now(),lease_token=NULL,
                            leased_until=NULL WHERE id=$1 AND lease_token=$2''', row['id'], lease)
                    else:
                        await tx.execute('''UPDATE bid_notices SET available_at=now()+$3*interval '1 second',
                            lease_token=NULL,leased_until=NULL WHERE id=$1 AND lease_token=$2''',
                            row['id'], lease, min(3600, 2 ** min(row['attempts'], 11)))
            try:
                await asyncio.wait_for(stop.wait(), timeout=.5)
            except TimeoutError:
                pass
    finally:
        await inbox.aclose()
        for client in app.state.bid_notice_clients.values():
            await client.aclose()
