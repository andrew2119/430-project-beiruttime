"""Explicit synthetic declarations and confirmed real offering scope."""
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CapabilityDeclaration:
    business_id: UUID
    business_revision: int
    scope: frozenset[str]
    synthetic: bool
    confirmation_ref: UUID | None = None
    confirmed_scope: frozenset[str] = frozenset()

    def permits(self, business_id, revision, scope, *, synthetic_release):
        if (business_id != self.business_id or revision != self.business_revision
                or not scope <= self.scope):
            return False
        if self.synthetic:
            return synthetic_release
        return bool(not synthetic_release and self.confirmation_ref
                    and scope <= self.confirmed_scope)
