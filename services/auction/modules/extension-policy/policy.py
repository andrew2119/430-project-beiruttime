"""Pure fixed-deadline policy; the canonical kernel owns admission and commit."""
from bt_contracts.auction.policy.models import AcceptedBidPolicy, ExtensionResult, ReserveBasis


def accepted_bid(state: dict) -> dict:
    value = AcceptedBidPolicy.model_validate(state)
    end = value.scheduled_ends_at if value.scheduled_ends_at is not None else value.ends_at
    if value.server_time >= end:
        raise ValueError('An accepted bid must precede authoritative close')
    # Stored legacy extension settings cannot change the scheduled deadline.
    return ExtensionResult(ends_at=end, end_version=value.end_version,
                           extended=False).model_dump(mode='json')


def extension(state: dict, bid: dict) -> dict:
    # Compatibility alias, including ceiling-only raises: time admission still applies.
    return accepted_bid({**state, 'server_time': bid['accepted_at']})


def reserve_met(*, current_minor: int, reserve_minor: int | None, accepted_sequence: int) -> bool:
    value = ReserveBasis(current_minor=current_minor, reserve_minor=reserve_minor,
                         accepted_sequence=accepted_sequence)
    # An unused private ceiling is never a public sale price or a reserve oracle.
    return (value.accepted_sequence > 0 and value.current_minor > 0
            and (value.reserve_minor is None or value.current_minor >= value.reserve_minor))
