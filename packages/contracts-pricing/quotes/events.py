"""Private assessed lifecycle facts, not work/payment/execution authority."""
from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt, model_validator
from bt_contracts_core.models import Contract


class AssessedQuoteFact(Contract):
    quote_id: UUID
    revision: StrictInt = Field(ge=1)
    source_id: UUID
    source_revision: StrictInt = Field(ge=1)
    buyer_id: UUID
    organization_id: UUID
    state: Literal['issued', 'accepted', 'declined_return_held', 'expired_return_held']
    assessment_id: UUID | None = None
    assessment_revision: StrictInt | None = Field(default=None, ge=1)
    selected_line_ids: list[UUID] | None = Field(default=None, max_length=40)
    total_minor: StrictInt | None = Field(default=None, gt=0, le=18_000_000_000_000)
    currency: Literal['USD', 'LBP'] | None = None
    terms_digest: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def accepted_binding(self):
        if self.state == 'accepted' and (not self.selected_line_ids or self.total_minor is None
                or self.currency is None or self.terms_digest is None or self.assessment_id is None
                or self.assessment_revision is None):
            raise ValueError('Accepted fact requires exact retained consent binding')
        if self.selected_line_ids and len(set(self.selected_line_ids)) != len(self.selected_line_ids):
            raise ValueError('Duplicate selected line')
        return self
