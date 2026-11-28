"""B-22: one occurrence, independent of delivery count or presentation language."""
import hashlib
import json
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
import jwt
from pydantic import ValidationError
from fastapi import APIRouter, HTTPException, Request
from bt_runtime.app.db import unit_of_work
from bt_events import consume
from bt_contracts_core.models import EventEnvelope
from bt_contracts.comms.inbox.v2 import PaymentActionRequiredV3, QuoteCreatedV3
from bt_contracts.comms.bid_notices.v2 import OutbidV2
from bt_contracts.comms.inbox.models import NoticeInput
from bt_contracts_core.errors import PublicError

NOTICE_TYPES = {'pricing.quote-created.v1': 'quote_ready',
               'orders.reservation-created.v1': 'reservation_ready', 'orders.payment-required.v1': 'payment_required',
               'trust.case-updated.v1': 'case_update'}

async def insert_notice(tx, event):
    try:
        notice = NoticeInput.model_validate(event.data)
    except ValidationError:
        raise PublicError('invalid_notice', 'Notice fields are invalid.', status=422) from None
    if NOTICE_TYPES[event.type] != notice.kind:
        raise PublicError('invalid_notice_kind', 'Notice type and category differ.', status=422)
    await persist_notice(tx, event.source, notice)


async def persist_notice(tx, source, notice):
    # Required categories cannot be opted out by a producer or optional preference.
    required = notice.kind != 'quote_ready'
    enabled = await tx.fetchval('SELECT optional_enabled FROM l07_notice_preferences WHERE owner_id=$1', notice.recipient_id)
    if not required and enabled is False:
        return
    await tx.execute('''INSERT INTO l07_notices(id,recipient_id,source,occurrence_id,kind,resource_id,resource_owner_id,resource_revision,event_time,required,sample)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT(recipient_id,source,occurrence_id) DO NOTHING''',
        uuid4(), notice.recipient_id, source, notice.occurrence_id, notice.kind, notice.resource_id,
        notice.resource_owner_id, notice.resource_revision, notice.event_time, required, notice.sample)

async def reviewed(tx, event):
    # Receipt only: review is not payment and must not manufacture a paid notice.
    pass

def handlers():
    return {'pricing.quote-created.v1': ('pricing', insert_notice),
            'pricing.quote-reviewed.v1': ('pricing', reviewed),
            'orders.reservation-created.v1': ('orders', insert_notice),
            'orders.payment-required.v1': ('orders', insert_notice),
            'trust.case-updated.v1': ('trust', insert_notice),
            'orders.payment-action-required.v3': ('orders', payment_required),
            'auction.outbid.v2': ('auction', outbid),
            'pricing.quote-created.v3': ('pricing', quote_created)}


def authorize(request, source):
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
        if claims['type'] != 'service' or claims['sub'] != source:
            raise HTTPException(403)
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None


def conflict():
    raise PublicError('notice_conflict', 'Notice facts differ. Review the original record.', status=409,
        details={'en': 'Review the original notice.', 'ar': 'راجع الإشعار الأصلي.'})


async def payment_required(tx, event):
    data = PaymentActionRequiredV3.model_validate(event.data)
    if event.subject != str(data.order_id):
        conflict()
    prior = await tx.fetchrow('SELECT * FROM l22_payment_notice_intents WHERE order_id=$1', data.order_id)
    if prior:
        if (prior['event_id'], prior['buyer_id'], prior['source_revision']) != (event.id, data.buyer_id, data.revision):
            conflict()
        return json.loads(prior['receipt']) if isinstance(prior['receipt'], str) else dict(prior['receipt'])
    notice_id = uuid5(NAMESPACE_URL, f'payment-notice:{event.id}:{data.buyer_id}:{data.order_id}')
    notified_at = await tx.fetchval('SELECT clock_timestamp()')
    await tx.execute('''INSERT INTO l07_notices(id,recipient_id,source,occurrence_id,kind,resource_id,
        resource_owner_id,resource_revision,event_time,received_at,required,sample)
        VALUES($1,$2,'orders',$3,'payment_required',$4,$2,$5,$6,$7,true,$8)''',
        notice_id, data.buyer_id, str(event.id), data.order_id, data.revision, event.time, notified_at, data.sample)
    await tx.execute('''INSERT INTO l22_verified_notice_deliveries VALUES($1,$2,$3,true)''',
        notice_id, data.buyer_id, notified_at)
    receipt = {'event_id': str(event.id), 'notice_id': str(notice_id), 'order_id': str(data.order_id),
        'buyer_id': str(data.buyer_id), 'notified_at': notified_at.isoformat(), 'verified_delivery_recorded': True}
    await tx.execute('''INSERT INTO l22_payment_notice_intents(event_id,notice_id,order_id,buyer_id,
        source_revision,notified_at,receipt,verified_delivery_recorded) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,true)''',
        event.id, notice_id, data.order_id, data.buyer_id, data.revision, notified_at, json.dumps(receipt))
    return receipt


async def outbid(tx, event):
    data = OutbidV2.model_validate(event.data)
    if event.subject != str(data.auction_id):
        conflict()
    await persist_notice(tx, event.source, NoticeInput(occurrence_id=str(event.id), recipient_id=data.recipient_id,
        kind='outbid', resource_id=data.auction_id, resource_owner_id=data.recipient_id,
        resource_revision=data.revision, event_time=event.time, sample=data.sample))


async def quote_created(tx, event):
    data = QuoteCreatedV3.model_validate(event.data)
    if data.kind != 'quote_ready' or event.subject != str(data.resource_id) or data.recipient_id != data.resource_owner_id:
        conflict()
    await persist_notice(tx, event.source, data)


async def receipt_schema_ready(tx):
    return await tx.fetchval("""SELECT to_regclass('l22_notice_events') IS NOT NULL
        AND to_regclass('l22_payment_notice_intents') IS NOT NULL
        AND to_regclass('l22_verified_notice_deliveries') IS NOT NULL""")


router = APIRouter()


@router.post('/internal/v1/inbox/events')
@router.post('/internal/v2/inbox/events')
async def receive(event: EventEnvelope, request: Request):
    registrations = handlers()
    authorize(request, event.source)
    registration = registrations.get(event.type)
    if registration is None or registration[0] != event.source:
        raise HTTPException(403)
    # Delivery request identifiers can vary; commercial event facts cannot.
    facts = event.model_dump(mode='json', exclude={'request_id'})
    fingerprint = hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()
    async with unit_of_work(request.app.state.pool, lock_key='notice-events') as tx:
        if not await receipt_schema_ready(tx):
            if event.type not in {*NOTICE_TYPES, 'pricing.quote-reviewed.v1'}:
                raise HTTPException(503)
            accepted = await consume(tx, 'L07.inbox', event, registration[1])
            return {'accepted': accepted}
        prior = await tx.fetchval('SELECT request_hash FROM l22_notice_events WHERE event_id=$1', event.id)
        if prior and prior != fingerprint:
            conflict()
        if not prior:
            try:
                result = await registration[1](tx, event)
            except ValidationError:
                raise PublicError('invalid_notice', 'Notice fields are invalid.', status=422,
                    details={'en': 'Reload the current record.', 'ar': 'أعد تحميل السجل الحالي.'}) from None
            await tx.execute('INSERT INTO l22_notice_events VALUES($1,$2)', event.id, fingerprint)
        elif event.type == 'orders.payment-action-required.v3':
            result = await payment_required(tx, event)
        else:
            result = None
    return {'accepted': not bool(prior), **({'receipt': result} if result else {})}


@router.get('/internal/v2/inbox/payment-notices/{event_id}')
async def lookup(event_id: UUID, request: Request):
    authorize(request, 'communications')
    async with request.app.state.pool.acquire() as tx:
        if not await receipt_schema_ready(tx):
            raise HTTPException(503)
        row = await tx.fetchrow('SELECT receipt,acknowledged_at FROM l22_payment_notice_intents WHERE event_id=$1', event_id)
    if row is None:
        raise HTTPException(404)
    return {'receipt': json.loads(row['receipt']) if isinstance(row['receipt'], str) else dict(row['receipt']),
        'state': 'acknowledged' if row['acknowledged_at'] else 'pending'}
