"""Private lifecycle commands; upstream receipts remain the availability authority."""
from dataclasses import asdict, dataclass
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class Command:
    operation_id: str
    subject_id: str
    watch_id: str
    actor_id: str
    organization_id: str | None
    expected_revision: int
    kind: Literal['pause', 'renew', 'relist']
    proof_id: str | None = None
    quote_id: str | None = None
    quote_revision: int | None = None
    policy_revision: str | None = None
    schema_version: str = 'listing-lifecycle.v1'

    def __post_init__(self):
        for value in (self.operation_id, self.subject_id, self.watch_id, self.actor_id):
            if not isinstance(value, str):
                raise ValueError('invalid_reference')
            UUID(value)
        if self.organization_id is not None:
            if not isinstance(self.organization_id, str):
                raise ValueError('invalid_reference')
            UUID(self.organization_id)
        if self.schema_version != 'listing-lifecycle.v1' or self.kind not in ('pause', 'renew', 'relist'):
            raise ValueError('invalid_command')
        if type(self.expected_revision) is not int or self.expected_revision < 1:
            raise ValueError('invalid_revision')
        if self.quote_revision is not None and (type(self.quote_revision) is not int or self.quote_revision < 1):
            raise ValueError('invalid_quote_revision')
        for value in (self.proof_id, self.quote_id, self.policy_revision):
            if value is not None and (not isinstance(value, str) or not value or len(value) > 128):
                raise ValueError('invalid_reference')
        if not self.proof_id:
            raise ValueError('possession_required')
        if self.kind != 'pause' and (
            not self.proof_id or not self.quote_id or not self.policy_revision
            or type(self.quote_revision) is not int or self.quote_revision < 1
        ):
            raise ValueError('renewal_prerequisites_required')

    def payload(self):
        return asdict(self)
