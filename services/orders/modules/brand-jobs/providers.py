"""Published producer ports; implementations must serialize final authority."""
from typing import Protocol, Any

class CurrentProviders(Protocol):
    async def check_access(self, command: Any) -> None:
        """Recheck actor, business membership and record permission or deny."""
        ...

    async def current_scope(self, command: Any) -> Any:
        """Read current acceptance, grant, allocation, assignment and Orders money.

        grant_current includes authoritative UTC expiry (strictly before expiry),
        serialized revocation and consumption state. For repair use S02 acceptance
        and O03 paid scope, without customization prerequisites. Never use a cache.
        """
        ...

    async def authorize_once(self, command: Any, scope: Any) -> dict:
        """Atomically recheck sources and persist job, receipt and outbox once.

        One watch and accepted scope may produce only one job across all operation
        references. A conflicting buyer or job is denied. Unknown money, withdrawn
        grants and invalid assignments are held with a responsible operator.
        A duplicate resolves its original effect even after a lost response.
        Never create another allocation, balance or payment attempt here.
        """
        ...

    async def lookup_operation(self, command: Any) -> dict | None:
        """Read canonical durable receipt by exact binding, without creating work.

        Authorized receipts include original job_id, assignee_id, binding and
        source_revision. Missing means no recorded effect; timeout is unknown.
        Assignment replacement requires a separate authoritative reconciliation.
        """
        ...

    async def assign_recovery(self, command: Any) -> dict:
        """Durably assign once per binding, returning operator_id, next_action,
        escalation_actor_id and authoritative UTC opened_at. Retrying returns
        the same assignment. The recovery owner executes the 24-hour response
        and 48-hour escalation schedule; reads never reset either deadline.
        """
        ...
