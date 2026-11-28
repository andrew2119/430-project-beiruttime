"""Current identity producer boundary, implemented by the identity steward."""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ContextManager, Protocol

@dataclass(frozen=True)
class Proof:
    actor_id: str
    change: Any
    verified_contact: bool
    recipient_verified: bool
    second_factor_verified: bool
    reauthenticated: bool
    issued_at: datetime
    expires_at: datetime

class Grant(Protocol):
    allowed: bool
    def verify(self, change: Any, *, timeout_seconds: int) -> Proof: ...

class Authority(Protocol):
    def lease(self, actor: str, subject: Any, organization: Any,
              *, timeout_seconds: int) -> ContextManager[Grant]: ...
