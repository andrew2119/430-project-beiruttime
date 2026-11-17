from uuid import NAMESPACE_URL, uuid5
from pydantic import ValidationError
from bt_contracts.auction.core.models import BidAcceptedEventData
from bt_contracts_core.errors import PublicError

async def accepted(tx, event):
    try:
        data = BidAcceptedEventData.model_validate(event.data)
    except ValidationError:
        raise PublicError('invalid_bid_event', 'The bid event is invalid.', status=422) from None
    if event.subject != str(data.auction_id):
        raise PublicError('invalid_bid_event', 'The bid event is invalid.', status=422)
    recipients = [(data.bidder_id, 'bid_accepted')]
    if data.previous_leader_id and data.previous_leader_id != data.leader_id:
        recipients.append((data.previous_leader_id, 'outbid'))
    if data.bidder_id != data.leader_id:
        recipients.append((data.bidder_id, 'outbid'))
    recipients = list(dict.fromkeys(recipients))
    for recipient, kind in recipients:
        notice_id = uuid5(NAMESPACE_URL, f'bid-notice:{event.id}:{recipient}:{kind}')
        await tx.execute('''INSERT INTO bid_notices(id,event_id,recipient_id,kind,auction_id,listing_id,
            sequence,current_minor,currency,ends_at,created_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
            ON CONFLICT(event_id,recipient_id,kind) DO NOTHING''', notice_id, event.id, recipient, kind,
            data.auction_id, data.listing_id, data.sequence, data.current_minor, data.currency, data.ends_at, event.time)
