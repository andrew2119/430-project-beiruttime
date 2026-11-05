"""Pure policy only; the canonical Auction kernel owns the lock, clock and commit."""
from datetime import timedelta
from bt_contracts.auction.policy.models import AcceptedBidPolicy, ExtensionResult, EXTENSION_SECONDS, WINDOW_SECONDS


def accepted_bid(state: dict) -> dict:
    value = AcceptedBidPolicy.model_validate(state)
    remaining = (value.ends_at - value.server_time).total_seconds()
    if remaining <= 0:
        raise ValueError('An accepted bid must precede authoritative close')
    extended = value.extension_policy == 'last-two-minutes.v1' and remaining <= WINDOW_SECONDS
    return ExtensionResult(ends_at=value.ends_at + timedelta(seconds=EXTENSION_SECONDS) if extended else value.ends_at,
        end_version=value.end_version + int(extended), extended=extended).model_dump(mode='json')


def extension(state: dict, bid: dict) -> dict:
    # Kernel v2 calls only for public bid rows. A private cap-only raise is not a competing bid.
    if bid.get('public_bid') is not True:
        return {'ends_at': state['ends_at'], 'end_version': state['end_version'], 'extended': False}
    return accepted_bid({**state, 'server_time': bid['accepted_at']})


def reserve_met(*, current_minor: int, reserve_minor: int | None, accepted_sequence: int) -> bool:
    # A private maximum is never the public sale price or a reserve oracle.
    return accepted_sequence > 0 and current_minor > 0 and (reserve_minor is None or current_minor >= reserve_minor)
