"""Orders' immutable fixed-price allocation attestation to Pricing v3."""

from uuid import UUID
from pydantic import AwareDatetime, Field, StrictInt
from bt_contracts_core.models import Contract


class QuoteCommitment(Contract):
    buyer_id: UUID
    order_id: UUID
    quote_revision: StrictInt = Field(ge=1)
    total_minor: StrictInt = Field(gt=0, le=18_000_000_000_000)
    committed_at: AwareDatetime
