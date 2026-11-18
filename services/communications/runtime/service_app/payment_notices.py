"""Durable required payment notices and stable simulated delivery receipts."""
import asyncio
import hashlib
import json
import os
import time
from uuid import UUID, uuid4

import jwt
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, StrictBool, StrictInt, ValidationError, model_validator
from bt_bulkheads import Unavailable
from bt_contracts_core.models import Contract, EventEnvelope
from .database import unit_of_work
from .operations import OPERATIONS, destinations

router = APIRouter()


class PaymentIntent(Contract):
    order_id: UUID
    buyer_id: UUID
    recipient_id: UUID
    revision: StrictInt = Field(gt=0, le=2147483647)
    required: StrictBool
    sample: StrictBool
    simulated: StrictBool

    @model_validator(mode='after')
    def validate_delivery(self):
        if self.recipient_id != self.buyer_id or not self.required or not self.simulated:
            raise ValueError('Payment notices require the buyer as recipient and simulated delivery')
        return self


def fingerprint(event):
    encoded = json.dumps(event.model_dump(mode='json', exclude={'request_id'}),
        sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(encoded.encode()).hexdigest()


def authorize(event, request):
    settings = request.app.state.settings
    if not settings.service_auth_public_key:
        raise HTTPException(503)
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    try:
        claims = jwt.decode(token, settings.service_auth_public_key, algorithms=['RS256'],
            issuer=settings.auth_issuer, audience='communications',
            options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'type']})
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None
    if (claims['type'], claims['sub'], event.source, event.type) != (
            'service', 'orders', 'orders', 'orders.payment-action-required.v3'):
        raise HTTPException(403)


def recovery_operator() -> UUID | None:
    try:
        return UUID(os.environ.get('BT_PAYMENT_NOTICE_OPERATOR_ID', ''))
    except ValueError:
        return None


async def persist(tx, event):
    try:
        intent = PaymentIntent.model_validate(event.data)
    except ValidationError:
        raise HTTPException(422) from None
    if event.subject != str(intent.order_id):
        raise HTTPException(409)
    # Lock the order across different event identifiers as well as duplicate delivery.
    await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'payment-notice:' + str(intent.order_id))
    prior = await tx.fetchrow('SELECT * FROM l22_payment_notices WHERE order_id=$1 OR event_id=$2',
        intent.order_id, event.id)
    digest = fingerprint(event)
    if prior:
        if prior['fingerprint'] != digest:
            raise HTTPException(409)
        return False
    notice_id = uuid4()
    notified_at = await tx.fetchval('''INSERT INTO l07_notices
        (id,recipient_id,source,occurrence_id,kind,resource_id,resource_owner_id,resource_revision,event_time,required,sample)
        VALUES($1,$2,'orders',$3,'payment_required',$4,$2,$5,$6,true,$7) RETURNING received_at''',
        notice_id, intent.buyer_id, str(event.id), intent.order_id, intent.revision, event.time, intent.sample)
    await tx.execute('''INSERT INTO l22_payment_notices
        (event_id,order_id,buyer_id,order_revision,fingerprint,notice_id,notified_at)
        VALUES($1,$2,$3,$4,$5,$6,$7)''',
        event.id, intent.order_id, intent.buyer_id, intent.revision, digest, notice_id, notified_at)
    await tx.execute('INSERT INTO inbox(consumer,event_id,source) VALUES($1,$2,$3)',
        'L22.payment-notices', event.id, event.source)
    return True


@router.post('/internal/v3/payment-events')
async def receive(event: EventEnvelope, request: Request):
    authorize(event, request)
    async with unit_of_work(request.app.state.pool) as tx:
        accepted = await persist(tx, event)
    return {'accepted': accepted}


def headers(app, audience, key):
    now = int(time.time())
    token = jwt.encode({'sub': 'communications', 'type': 'service',
        'iss': app.state.settings.auth_issuer, 'aud': audience, 'iat': now, 'exp': now + 60}, key, algorithm='RS256')
    return {'Authorization': 'Bearer ' + token}


def verified_contact(data, buyer_id):
    if data.get('subject_id') != str(buyer_id) or type(data.get('revision')) is not int or data['revision'] <= 0:
        return None
    for channel in ('email', 'phone'):
        recipient = data.get(channel)
        if isinstance(recipient, str) and 0 < len(recipient) <= 254 and data.get(channel + '_sample') is True:
            return data['revision'], channel, hashlib.sha256(recipient.encode()).hexdigest()
    return None


def receipt(row):
    return {key: str(row[key]) for key in ('event_id', 'notice_id', 'order_id', 'buyer_id')} | {
        'notified_at': row['notified_at'].isoformat(), 'verified_delivery_recorded': True}


async def deliver(app, row, lease, key):
    if not row['verified_delivery_recorded']:
        result = await app.state.identity.request('GET',
            '/internal/v1/contacts/' + str(row['buyer_id']) + '/delivery', headers=headers(app, 'identity', key))
        if isinstance(result, Unavailable) or result.status_code != 200:
            return False
        try:
            contact = verified_contact(result.json(), row['buyer_id'])
        except (ValueError, AttributeError, TypeError):
            return False
        if contact is None:
            return False
        # Commit the synthetic verified-recipient record before the Orders call.
        async with unit_of_work(app.state.pool) as tx:
            updated = await tx.fetchval('''UPDATE l22_payment_notices SET
                contact_revision=$3,channel=$4,recipient_digest=$5,verified_delivery_recorded=true
                WHERE event_id=$1 AND lease_token=$2 RETURNING event_id''', row['event_id'], lease, *contact)
        if updated is None:
            return False
    operation = OPERATIONS['payment-notice.v3']
    result = await app.state.orders.request(operation.method, operation.path,
        json=receipt(row), headers=headers(app, 'orders', key))
    return not isinstance(result, Unavailable) and 200 <= result.status_code < 300


async def hold_for_recovery(tx, row):
    await tx.execute('''INSERT INTO l22_payment_notice_recovery
        (event_id,operator_id,held_since,response_due_at,escalation_due_at)
        VALUES($1,$2,$3::timestamptz,$3::timestamptz+interval '24 hours',$3::timestamptz+interval '48 hours')
        ON CONFLICT (event_id) DO UPDATE SET operator_id=EXCLUDED.operator_id
        WHERE l22_payment_notice_recovery.operator_id IS NULL AND EXCLUDED.operator_id IS NOT NULL''',
        row['event_id'], recovery_operator(), row['notified_at'])


async def update_recovery(tx):
    # Retries and restarts never reset ownership or either deadline.
    await tx.execute('''UPDATE l22_payment_notice_recovery r SET
        escalated_at=COALESCE(r.escalated_at,now()),
        next_action_en='Escalated: review verified contact and the retained Orders receipt; retry the same receipt.',
        next_action_ar='تم التصعيد: راجع جهة الاتصال المثبتة وإيصال الطلبات المحفوظ؛ أعد محاولة الإيصال نفسه.'
        FROM l22_payment_notices n WHERE r.event_id=n.event_id
        AND n.acknowledged_at IS NULL AND r.escalation_due_at<=now()
        AND r.resolved_at IS NULL''')


async def tick(app, key):
    lease = uuid4()
    async with unit_of_work(app.state.pool) as tx:
        await update_recovery(tx)
        rows = await tx.fetch('''WITH due AS (SELECT event_id FROM l22_payment_notices
            WHERE acknowledged_at IS NULL AND available_at<=now()
            AND (leased_until IS NULL OR leased_until<now())
            ORDER BY available_at,event_id FOR UPDATE SKIP LOCKED LIMIT 4)
            UPDATE l22_payment_notices n SET lease_token=$1,leased_until=now()+interval '30 seconds',attempts=attempts+1
            FROM due WHERE n.event_id=due.event_id RETURNING n.*''', lease)
    for row in rows:
        ok = key is not None and await deliver(app, row, lease, key)
        async with unit_of_work(app.state.pool) as tx:
            updated = await tx.fetchval('''UPDATE l22_payment_notices SET
                acknowledged_at=CASE WHEN $3 THEN now() ELSE acknowledged_at END,
                available_at=now()+$4*interval '1 second',lease_token=NULL,leased_until=NULL
                WHERE event_id=$1 AND lease_token=$2 RETURNING event_id''', row['event_id'], lease, ok,
                min(3600, 2 ** min(row['attempts'], 11)))
            if updated is None:
                continue
            if not ok:
                await hold_for_recovery(tx, row)
                continue
            await tx.execute('''UPDATE l22_payment_notice_recovery r SET resolved_at=now()
                FROM l22_payment_notices n WHERE r.event_id=n.event_id
                AND n.event_id=$1 AND n.acknowledged_at IS NOT NULL
                AND r.resolved_at IS NULL''', row['event_id'])


async def run(app, stop):
    key = os.environ.get('BT_SERVICE_AUTH_PRIVATE_KEY', '')
    # Runtime discovery mounts this receiver before worker startup.
    subscribed = frozenset({'payment-notice.v3'}) if any(
        route.path == '/internal/v3/payment-events' and route.endpoint is receive
        for route in app.routes) else frozenset()
    destinations(subscribed, frozenset({'payment-notice.v3'}))
    while not stop.is_set():
        await tick(app, key or None)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1)
        except TimeoutError:
            pass
