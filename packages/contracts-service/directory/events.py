"""Care event data V1: receipt-only opaque references, never a buyer notice or approval."""
from uuid import UUID
from pydantic import Field
from bt_contracts_core.models import Contract


class CareEventData(Contract):
    resource_id: UUID
    revision: int = Field(strict=True, ge=1, le=2147483647)


PRODUCERS = {
    'service.directory-published.v1': 'service-operations',
    'service.directory-choice-saved.v1': 'service-operations',
    'catalog.movement-published.v1': 'catalog',
    'catalog.movement-selected.v1': 'catalog',
}
