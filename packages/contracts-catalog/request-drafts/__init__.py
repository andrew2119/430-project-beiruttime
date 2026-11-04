from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt, field_validator, model_validator
from bt_contracts_core.models import Contract


class DraftInput(Contract):
    brand_id: UUID | None = None
    kind: Literal['customization','service']
    watch_context: Literal['owned_watch','seller_base','undecided'] = 'undecided'
    watch_reference: str = Field(default='',max_length=300)
    scope_intent: str = Field(default='',max_length=1000)
    notes: str = Field(default='',max_length=4000)
    options: dict[str,str] = Field(default_factory=dict,max_length=5)
    configuration_id: UUID | None = None
    configuration_revision: StrictInt | None = Field(default=None,ge=1,le=2147483647)

    @model_validator(mode='after')
    def paired_configuration(self):
        if (self.configuration_id is None)!=(self.configuration_revision is None):
            raise ValueError('Configuration id and revision must be paired')
        return self

    @field_validator('options')
    @classmethod
    def bounded_options(cls,value):
        if set(value)-{'color','material','movement','dial','sophistication'} or any(len(v)>100 for v in value.values()):
            raise ValueError('Unknown or oversized option')
        return value


class DraftUpdate(DraftInput):
    expected_revision: StrictInt = Field(ge=1)
