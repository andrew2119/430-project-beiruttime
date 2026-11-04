"""Catalog v1 listing commands. Monetary values use integer minor units."""

from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Modification(Wire):
    component: str = Field(min_length=1, max_length=100)
    provenance: Literal["genuine", "aftermarket", "reworked", "unknown"]
    modifier: str = Field(min_length=1, max_length=160)
    warranty_issuer: str = Field(min_length=1, max_length=160)
    notes: str = Field(default="", max_length=1000)


class WatchFacts(Wire):
    brand: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=160)
    reference: str = Field(default="", max_length=100)
    year: StrictInt | None = Field(default=None, ge=1800, le=2100)
    condition: str = Field(default="", max_length=2000)
    component_wear: dict[Literal["case", "dial", "crystal", "bracelet", "movement"], str] = Field(default_factory=dict)
    location: str = Field(default="", max_length=160)
    included: list[Literal["box", "papers", "links"]] = Field(default_factory=list, max_length=3)
    no_documents: bool = True
    modified: bool | None = None
    modifications: list[Modification] = Field(default_factory=list, max_length=20)
    ownership_confirmed: bool = False
    sale_mode: Literal["fixed_price", "auction", "offer"] = "fixed_price"
    currency: Literal["USD"] = "USD"
    price_minor: StrictInt | None = Field(default=None, ge=1, le=10**12)

    @model_validator(mode="after")
    def bounded_wear(self):
        if any(len(value) > 1000 for value in self.component_wear.values()):
            raise ValueError("Component notes exceed the field budget")
        if len(set(self.included)) != len(self.included):
            raise ValueError("Duplicate included item")
        return self


class CreateDraft(Wire):
    facts: WatchFacts = Field(default_factory=WatchFacts)
    demo_key: str | None = Field(default=None, pattern=r"^DEMO-WATCH-0[1-6]$")


class SaveDraft(Wire):
    facts: WatchFacts


class Gallery(Wire):
    photo_ids: list[UUID] = Field(min_length=1, max_length=12)
    cover_id: UUID


class Publish(Wire):
    fee_quote_id: UUID
    rules_version: str = Field(min_length=1, max_length=100)


def incomplete(facts: WatchFacts, photo_count: int) -> list[str]:
    missing = [
        key
        for key in ("brand", "model", "reference", "year", "condition", "location", "price_minor")
        if not getattr(facts, key)
    ]
    if not any(value.strip() for value in facts.component_wear.values()):
        missing.append("component_wear")
    if not facts.ownership_confirmed:
        missing.append("ownership_confirmed")
    if facts.modified is None:
        missing.append("modified")
    if facts.modified and not facts.modifications:
        missing.append("modifications")
    if not facts.modified and facts.modifications:
        missing.append("modified")
    if photo_count < 1:
        missing.append("photos")
    return list(dict.fromkeys(missing))
