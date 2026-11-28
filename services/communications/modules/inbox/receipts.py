"""Bounded delivery of immutable committed availability receipts."""
import asyncio
import json
import os
import time
from uuid import uuid4
import jwt
from bt_bulkheads import DependencyClient, Unavailable
from bt_contracts.comms.inbox.v2 import PaymentNoticeReceiptV3
from .events import receipt_schema_ready


def decoded(value):
    return json.loads(value) if isinstance(value, str) else dict(value)


async def tick(pool, orders, headers):
    lease = uuid4()
    async with pool.acquire() as tx:
        if not await receipt_schema_ready(tx):
            return
        rows = await tx.fetch('''WITH due AS (
            SELECT event_id FROM l22_payment_notice_intents WHERE acknowledged_at IS NULL
            AND available_at<=now() AND (leased_until IS NULL OR leased_until<now())
            ORDER BY available_at,event_id FOR UPDATE SKIP LOCKED LIMIT 8)
            UPDATE l22_payment_notice_intents n SET lease_token=$1,
            leased_until=now()+interval '30 seconds',attempts=attempts+1
            FROM due WHERE n.event_id=due.event_id RETURNING n.*''', lease)
    for row in rows:
        receipt = decoded(row['receipt'])
        ok = False
        try:
            response = await orders.request('POST', '/internal/v3/payment-notices', json=receipt,
                headers={**headers(), 'Idempotency-Key': str(row['event_id'])})
            if not isinstance(response, Unavailable) and 200 <= response.status_code < 300:
                ok = PaymentNoticeReceiptV3.model_validate(response.json()) == PaymentNoticeReceiptV3.model_validate(receipt)
        except (ValueError, TypeError):
            pass
        async with pool.acquire() as tx:
            if ok:
                await tx.execute('''UPDATE l22_payment_notice_intents SET acknowledged_at=now(),
                    lease_token=NULL,leased_until=NULL WHERE event_id=$1 AND lease_token=$2''', row['event_id'], lease)
            else:
                await tx.execute('''UPDATE l22_payment_notice_intents SET lease_token=NULL,leased_until=NULL,
                    available_at=now()+$3*interval '1 second' WHERE event_id=$1 AND lease_token=$2''',
                    row['event_id'], lease, min(3600, 2 ** min(row['attempts'], 11)))


async def run(app, stop):
    key = os.environ.get('BT_SERVICE_AUTH_PRIVATE_KEY', '')
    if not key:
        await stop.wait()
        return
    orders = DependencyClient('orders', os.environ.get('ORDERS_API_URL', 'http://orders:8000'), timeout=1.2, concurrency=1)

    def headers():
        now = int(time.time())
        token = jwt.encode({'sub': 'communications', 'type': 'service', 'aud': 'orders',
            'iss': app.state.settings.auth_issuer, 'iat': now, 'exp': now+60}, key, algorithm='RS256')
        return {'Authorization': 'Bearer '+token}

    try:
        while not stop.is_set():
            await tick(app.state.pool, orders, headers)
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
    finally:
        await orders.aclose()
