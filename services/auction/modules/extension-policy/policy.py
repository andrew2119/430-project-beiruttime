"""Pure fixed-deadline policy; the canonical kernel owns admission and commit."""
from bt_contracts.auction.policy.models import AcceptedBidPolicy, ExtensionResult


def accepted_bid(state: dict) -> dict:
    value = AcceptedBidPolicy.model_validate(state)
    if value.server_time >= value.ends_at:
        raise ValueError('An accepted bid must precede authoritative close')
    # Stored legacy extension settings cannot change the scheduled deadline.
    return ExtensionResult(ends_at=value.ends_at, end_version=value.end_version,
                           extended=False).model_dump(mode='json')


def extension(state: dict, bid: dict) -> dict:
    # Compatibility alias, including ceiling-only raises: time admission still applies.
    return accepted_bid({**state, 'server_time': bid['accepted_at']})


def reserve_met(*, current_minor: int, reserve_minor: int | None, accepted_sequence: int) -> bool:
    # An unused private ceiling is never a public sale price or a reserve oracle.
    return accepted_sequence > 0 and current_minor > 0 and (reserve_minor is None or current_minor >= reserve_minor)
