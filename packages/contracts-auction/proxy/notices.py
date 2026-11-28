"""Notice recipients derived from validated accepted-bid event identities."""
from typing import Literal, TypeVar
from uuid import UUID

BidderId = TypeVar('BidderId', str, UUID)


def outbid_recipients(
    *, bidder_id: BidderId, previous_leader_id: BidderId | None, leader_id: BidderId,
) -> list[BidderId]:
    """Return each displaced leader or beaten challenger once per event."""
    return list(dict.fromkeys(
        recipient for recipient in (previous_leader_id, bidder_id)
        if recipient is not None and recipient != leader_id
    ))


def accepted_bid_notices(
    *, bidder_id: BidderId, previous_leader_id: BidderId | None, leader_id: BidderId,
) -> list[tuple[BidderId, Literal['bid_accepted', 'outbid']]]:
    """Build the notice plan from a validated canonical event."""
    notices: list[tuple[BidderId, Literal['bid_accepted', 'outbid']]] = [(bidder_id, 'bid_accepted')]
    notices.extend((recipient, 'outbid') for recipient in outbid_recipients(
        bidder_id=bidder_id, previous_leader_id=previous_leader_id, leader_id=leader_id,
    ))
    return notices
