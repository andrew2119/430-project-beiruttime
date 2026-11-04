"""Receipt-only Catalog option events; no private evidence or recipient authority."""
from uuid import UUID
from pydantic import Field
from bt_contracts_core.models import Contract


class OptionEventData(Contract):
    resource_id: UUID
    revision: int = Field(ge=1, le=2147483647, strict=True)


EVENT_TYPES = (
    'catalog.brand-option-published.v1',
    'catalog.brand-selection-saved.v1',
    'catalog.brand-reference-saved.v1',
)
SOURCE = 'catalog'
