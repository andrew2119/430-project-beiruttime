"""B-22: one occurrence, independent of delivery count or presentation language."""
from uuid import uuid4
from pydantic import ValidationError
from fastapi import APIRouter
from bt_runtime.event_http import build_event_router
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
            'trust.case-updated.v1': ('trust', insert_notice)}


# Reuse the foundation's authenticated receiver unchanged under Inbox's distinct
# namespace. L05's frozen bid-notices module owns /internal/v1/events.
_receiver = build_event_router('L07.inbox', handlers())
router = APIRouter()
router.add_api_route('/internal/v1/inbox/events',
    next(route.endpoint for route in _receiver.routes if route.path == '/internal/v1/events'), methods=['POST'])
