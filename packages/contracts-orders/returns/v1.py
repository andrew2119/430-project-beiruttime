"""Private return commands. Source facts are revalidated for every access."""
from dataclasses import dataclass
from typing import Literal

VERSION = 'orders.returns.v1'
STATES = ('requested', 'permitted', 'declined', 'unresolved', 'received', 'refund_pending', 'refunded')

@dataclass(frozen=True)
class Command:
    operation_id: str
    subject_id: str
    watch_id: str
    actor_id: str
    organization_id: str
    expected_revision: int
    kind: Literal['request', 'permit', 'decline', 'receive', 'refund_pending', 'refunded']
    source_revision: int
    policy_revision: str
    reason: str
    receipt_id: str = ''

    def validate(self):
        validate(self)


def validate(command):
    for name in ('operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'policy_revision', 'reason'):
        value = getattr(command, name)
        if not isinstance(value, str) or not value.strip() or len(value) > (1000 if name == 'reason' else 128):
            raise ValueError('invalid')
    if command.kind not in ('request', 'permit', 'decline', 'receive', 'refund_pending', 'refunded'):
        raise ValueError('invalid')
    for value in (command.expected_revision, command.source_revision):
        if type(value) is not int or value < 0:
            raise ValueError('invalid')
    if not isinstance(command.receipt_id, str) or len(command.receipt_id) > 128:
        raise ValueError('invalid')
