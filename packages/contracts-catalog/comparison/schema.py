"""Comparison v1: a bounded public read, never commitment authority."""
from typing import Annotated, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

Identifier = Annotated[str, Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')]
Revision = Annotated[StrictInt, Field(ge=1, le=9_000_000_000_000_000)]
Minor = Annotated[StrictInt, Field(ge=0, le=1_000_000_000_000)]


class Closed(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)


class Text(Closed):
    en: str = Field(min_length=1, max_length=2000)
    ar: str = Field(min_length=1, max_length=2000)


class Selection(Closed):
    watch_id: Identifier
    expected_revision: Revision | None = None


class CompareRequest(Closed):
    schema_version: Literal['comparison.v1'] = 'comparison.v1'
    selections: list[Selection] = Field(max_length=3)

    @model_validator(mode='after')
    def unique(self):
        if len({item.watch_id for item in self.selections}) != len(self.selections):
            raise ValueError('Duplicate selection')
        return self


class Modification(Closed):
    component: Text
    provenance: Text
    modifier: Text
    warranty_issuer: Text


class Facts(Closed):
    title: Text
    brand: Text
    model: Text
    reference: str | None = Field(default=None, max_length=100)
    year: Annotated[StrictInt, Field(ge=1800, le=2100)] | None = None
    condition: Text
    component_wear: list[Text] = Field(max_length=5)
    included: list[Literal['box', 'papers', 'links']] = Field(max_length=3)
    seller_type: Literal['private', 'dealer', 'brand']
    modified: StrictBool
    modifications: list[Modification] = Field(max_length=20)
    authentication: Literal['not_inspected', 'pending', 'passed', 'failed', 'inconclusive', 'unavailable']
    price_minor: Minor | None = None
    buyer_fee_minor: Minor | None = None
    total_minor: Minor | None = None
    currency: Literal['USD'] = 'USD'
    price_basis: Literal['fixed', 'auction', 'offer', 'unavailable']
    economics_revision: Identifier | None = None
    demo: StrictBool

    @model_validator(mode='after')
    def disclosures(self):
        if len(set(self.included)) != len(self.included) or self.modified != bool(self.modifications):
            raise ValueError('Inconsistent disclosures')
        if self.seller_type != 'private' and self.authentication not in ('not_inspected', 'unavailable'):
            raise ValueError('Business status is not independent watch authentication')
        amounts = (self.price_minor, self.buyer_fee_minor, self.total_minor)
        if any(value is not None for value in amounts):
            if any(value is None for value in amounts) or not self.economics_revision:
                raise ValueError('Incomplete economics')
            if self.total_minor != self.price_minor + self.buyer_fee_minor:
                raise ValueError('Inconsistent economics')
        return self


class Column(Closed):
    watch_id: Identifier
    expected_revision: Revision | None = None
    state: Literal['available', 'unavailable', 'pending', 'denied', 'stale']
    revision: Revision | None = None
    facts: Facts | None = None

    @model_validator(mode='after')
    def safe_column(self):
        if (self.state == 'available') != (self.facts is not None):
            raise ValueError('Only a currently public column has facts')
        if self.state == 'available' and self.revision is None:
            raise ValueError('Missing source revision')
        return self


class Comparison(Closed):
    schema_version: Literal['comparison.v1'] = 'comparison.v1'
    operation_id: Identifier
    server_time: AwareDatetime
    columns: list[Column] = Field(max_length=3)
