"""The frozen same-Catalog public view. Never select the private base table."""
import json
from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field, StrictBool, StrictInt, model_validator
from .models import PublicModel

SOURCE = 'catalog_public_listings_v1'
COLUMNS = 'id,seller_id,organization_id,seller_type,seller_label,physical_watch_id,revision,status,facts,photo_ids,cover_id,is_demo,registration,rules_version,published_at'

class Modification(PublicModel):
    component: str = Field(min_length=1,max_length=100)
    provenance: Literal['genuine','aftermarket','reworked','unknown']
    modifier: str = Field(min_length=1,max_length=160)
    warranty_issuer: str = Field(min_length=1,max_length=160)
    notes: str = Field(default='',max_length=1000)

class Facts(PublicModel):
    brand: str = Field(min_length=1,max_length=100)
    model: str = Field(min_length=1,max_length=160)
    reference: str = Field(max_length=100)
    year: StrictInt | None = Field(ge=1800,le=2100)
    condition: str = Field(max_length=2000)
    component_wear: dict[Literal['case','dial','crystal','bracelet','movement'],str]
    location: str = Field(min_length=1,max_length=160)
    included: list[Literal['box','papers','links']] = Field(max_length=3)
    no_documents: StrictBool
    modified: StrictBool | None
    modifications: list[Modification] = Field(max_length=20)
    ownership_confirmed: StrictBool
    sale_mode: Literal['fixed_price','auction','offer']
    currency: Literal['USD']
    price_minor: StrictInt | None = Field(ge=1,le=1_000_000_000_000)

class Registration(PublicModel):
    watch_id: UUID
    listing_id: UUID
    sale_mode: Literal['fixed','auction','seller_base']
    revision: StrictInt = Field(ge=1)

class PublicListing(PublicModel):
    id: UUID
    seller_id: UUID
    organization_id: UUID | None
    seller_type: Literal['private','dealer','brand']
    seller_label: str = Field(min_length=1,max_length=160)
    physical_watch_id: UUID
    revision: StrictInt = Field(ge=1)
    status: Literal['published']
    facts: Facts
    photo_ids: list[UUID] = Field(min_length=1,max_length=12)
    cover_id: UUID
    is_demo: StrictBool
    registration: Registration
    rules_version: str = Field(min_length=1,max_length=100)
    published_at: AwareDatetime

    @model_validator(mode='after')
    def bindings(self):
        if self.facts.no_documents == ('papers' in self.facts.included):
            raise ValueError('Conflicting document declaration')
        proof=self.registration
        if proof.watch_id!=self.physical_watch_id or proof.listing_id!=self.id or proof.sale_mode!={'fixed_price':'fixed','auction':'auction','offer':'seller_base'}[self.facts.sale_mode]:
            raise ValueError('Publication registration binding changed')
        if self.cover_id not in self.photo_ids or len(set(self.photo_ids))!=len(self.photo_ids):
            raise ValueError('Invalid public gallery binding')
        if (self.seller_type=='private')!=(self.organization_id is None):
            raise ValueError('Invalid public seller scope')
        if self.facts.modified is None or self.facts.modified!=bool(self.facts.modifications):
            raise ValueError('Incomplete modification disclosure')
        return self


def parse_row(row) -> PublicListing:
    data=dict(row)
    for field in ('facts','registration'):
        if isinstance(data[field],str):data[field]=json.loads(data[field])
    return PublicListing.model_validate(data)
