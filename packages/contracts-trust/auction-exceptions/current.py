"""Private exceptional-action contract, version 1."""
from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class Command:
    operation_id: str
    subject_id: str
    watch_id: str
    actor_id: str
    organization_id: str
    expected_revision: int
    action: Literal['cancel', 'retract', 'remove_bid', 'seller_end']
    reason: str
    target_bidder_id: str | None
    quote_id: str
    quote_revision: int
    policy_revision: int
    assignment_revision: int

    def __post_init__(self):
        for name in ('operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'quote_id'):
            value = getattr(self, name)
            if not isinstance(value, str) or not 1 <= len(value) <= 128:
                raise ValueError('invalid_reference')
        for name in ('expected_revision', 'quote_revision', 'policy_revision', 'assignment_revision'):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 2**53 - 1:
                raise ValueError('invalid_revision')
        if self.action not in ('cancel', 'retract', 'remove_bid', 'seller_end'):
            raise ValueError('invalid_action')
        if not isinstance(self.reason, str) or not 10 <= len(self.reason.strip()) <= 2000:
            raise ValueError('reason_required')
        if self.action in ('retract', 'remove_bid') and not self.target_bidder_id:
            raise ValueError('target_required')
        if self.target_bidder_id is not None and (not isinstance(self.target_bidder_id, str) or not 1 <= len(self.target_bidder_id) <= 128):
            raise ValueError('invalid_target')

    def payload(self):
        return asdict(self)
