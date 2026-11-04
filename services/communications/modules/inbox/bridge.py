"""L05 compatibility bridge. Same-service durable delivery, never a public publisher."""
from typing import Literal
from uuid import UUID
import jwt
from fastapi import APIRouter, HTTPException, Request
from pydantic import AwareDatetime, Field, StrictInt
from bt_contracts_core.models import Contract, EventEnvelope
from bt_contracts.comms.inbox.models import NoticeInput
from bt_events import consume
from bt_runtime.app.db import unit_of_work
from .events import persist_notice

router = APIRouter(tags=['internal-notice-bridge'])


class BidData(Contract):
    current_minor: StrictInt = Field(gt=0, le=9_000_000_000_000_000)
    currency: Literal['USD', 'LBP']
    ends_at: AwareDatetime
    sequence: StrictInt = Field(ge=1)


class BridgeNotice(Contract):
    id: UUID
    recipient_id: UUID
    kind: Literal['accepted', 'bid_accepted', 'outbid']
    resource_type: Literal['auction']
    resource_id: UUID
    href: str = Field(pattern=r'^/watches/[0-9a-fA-F-]{36}$')
    created_at: AwareDatetime
    data: BidData
    resource_revision: StrictInt | None = Field(default=None, ge=1)


def service_authorized(request):
    settings = request.app.state.settings
    if not settings.service_auth_public_key:
        raise HTTPException(503)
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token or len(token) > 8192:
        raise HTTPException(401)
    try:
        claims = jwt.decode(token, settings.service_auth_public_key, algorithms=['RS256'], issuer=settings.auth_issuer,
            audience='communications', options={'require': ['exp', 'iat', 'iss', 'aud', 'sub', 'type']})
        if claims['type'] != 'service' or claims['sub'] != 'communications':
            raise HTTPException(403)
    except jwt.InvalidTokenError:
        raise HTTPException(401) from None


@router.post('/internal/v1/notices')
async def bridge(body: BridgeNotice, request: Request):
    service_authorized(request)
    notice = NoticeInput(occurrence_id=str(body.id), recipient_id=body.recipient_id,
        kind='outbid' if body.kind == 'outbid' else 'bid_accepted', resource_id=body.resource_id,
        resource_owner_id=body.recipient_id, resource_revision=body.resource_revision,
        event_time=body.created_at, required=True)
    event = EventEnvelope(id=body.id, type='communications.bid-notice.v1', source='communications',
        subject=str(body.resource_id), time=body.created_at, request_id=request.state.request_id, data=notice.model_dump(mode='json'))
    async def store(tx, envelope):
        await persist_notice(tx, envelope.source, notice)
    async with unit_of_work(request.app.state.pool) as tx:
        accepted = await consume(tx, 'L07.bid-notice-bridge', event, store)
    # Ignore caller href for navigation: GET destination rechecks Auction's canonical listing projection.
    return {'accepted': accepted}
