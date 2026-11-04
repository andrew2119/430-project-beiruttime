"""Catalog brand-options V1. Saved intent is never a feasibility approval."""

from typing import Literal
from uuid import UUID
from pydantic import Field, StrictInt, StringConstraints
from typing_extensions import Annotated
from bt_contracts_core.models import Contract

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=300)]
Kind = Literal["color", "material", "dial", "sophistication"]


class Localized(Contract):
    en: Text
    ar: Text


class OptionWrite(Contract):
    expected_revision: StrictInt = Field(ge=0, le=2147483646)
    component: Literal["case", "bezel", "dial", "hands", "markers", "strap", "bracelet", "package"]
    label: Localized
    base_models: list[Identifier] = Field(min_length=1, max_length=20)
    calibers: list[Identifier] = Field(min_length=1, max_length=20)
    available: bool = True
    details: dict = Field(max_length=16)


class SelectionWrite(Contract):
    brand_id: UUID
    base_model: Identifier
    caliber: Identifier
    option_id: UUID
    option_revision: StrictInt = Field(ge=1, le=2147483647)
    expected_revision: StrictInt = Field(ge=0, le=2147483646)
    component: Literal["case", "bezel", "dial", "hands", "markers", "strap", "bracelet", "package"]
    reference_ids: list[UUID] = Field(default_factory=list, max_length=3)


class ColorDetails(Contract):
    color: Localized
    finish: Localized
    coating: Localized | None = None
    swatch: Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class MaterialDetails(Contract):
    material: Localized
    grade: Text
    construction: Literal["solid", "plating", "coating"]
    substrate: Localized | None = None
    thickness_micrometers: int | None = Field(default=None, ge=1, le=1000)


class DialDetails(Contract):
    dial: Localized
    hands: Localized
    markers: Localized
    provenance: Literal["original", "aftermarket"]
    source_reference: Text


class SophisticationDetails(Contract):
    interventions: list[Localized] = Field(min_length=1, max_length=12)
    exclusions: list[Localized] = Field(min_length=1, max_length=12)
    required_tests: list[Localized] = Field(min_length=1, max_length=12)
    price_reference: Identifier
    price_minor: StrictInt = Field(ge=0, le=999999999999)
    currency: Literal["USD", "LBP"]
    conversion: Literal["none"] = "none"
