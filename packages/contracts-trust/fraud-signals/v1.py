"""Private observable-source contract. No image bytes or auction ceilings."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, AwareDatetime

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

class Photo(Strict):
    photo_id: str = Field(min_length=1, max_length=128)
    normalized_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    normalization_version: Literal['v1']
    watch_id: str = Field(min_length=1, max_length=128)
    seller_id: str = Field(min_length=1, max_length=128)

class Bid(Strict):
    bid_id: str = Field(min_length=1, max_length=128)
    auction_id: str = Field(min_length=1, max_length=128)
    bidder_id: str = Field(min_length=1, max_length=128)
    seller_id: str = Field(min_length=1, max_length=128)
    accepted_at: AwareDatetime
    automatic: bool

class Scan(Strict):
    schema_version: Literal['fraud-signals.v1']
    operation_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,128}$')
    subject_id: str = Field(min_length=1, max_length=128)
    watch_id: str = Field(min_length=1, max_length=128)
    organization_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0, le=2147483647)
    source_revision: int = Field(ge=1, le=2147483647)
