from uuid import NAMESPACE_URL, uuid5
from pydantic import ValidationError
from bt_contracts.auction.core.models import BidAcceptedEventData
from bt_contracts.comms.bid_notices.v2 import BidOutbidV2
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
            sequence,current_minor,currency,ends_at,created_at,source_revision) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT(event_id,recipient_id,kind) DO NOTHING''', notice_id, event.id, recipient, kind,
            data.auction_id, data.listing_id, data.sequence, data.current_minor, data.currency, data.ends_at, event.time, data.revision)


async def bid_outbid(tx, event):
    try:
        data = BidOutbidV2.model_validate(event.data)
    except ValidationError:
        raise PublicError('invalid_bid_event', 'The bid event is invalid.', status=422) from None
    if event.subject != str(data.auction_id):
        raise PublicError('invalid_bid_event', 'The bid event is invalid.', status=422)
    # The same occurrence already has a durable bridge row from bid-accepted.
    # Allow either relay order and leave delivery pending until that row exists.
    row = await tx.fetchrow('''SELECT n.id,n.listing_id,n.current_minor,n.currency,n.source_revision
        FROM bid_notices n JOIN bid_notices a ON a.event_id=n.event_id AND a.recipient_id=n.recipient_id
        AND a.kind='bid_accepted'
        WHERE n.auction_id=$1 AND n.sequence=$2 AND n.recipient_id=$3 AND n.kind='outbid'
        FOR UPDATE OF n''', data.auction_id, data.sequence, data.bidder_id)
    if not row:
        raise PublicError('bid_occurrence_pending', 'The accepted bid occurrence is unavailable.', status=503)
    if (row['listing_id'], row['current_minor'], row['currency']) != (data.listing_id, data.current_minor, data.currency):
        raise PublicError('invalid_bid_event', 'The bid occurrence facts differ.', status=422)
    if row['source_revision'] is None:
        await tx.execute('UPDATE bid_notices SET source_revision=$2 WHERE id=$1', row['id'], data.revision)
    elif row['source_revision'] != data.revision:
        raise PublicError('invalid_bid_event', 'The bid occurrence revision differs.', status=422)
