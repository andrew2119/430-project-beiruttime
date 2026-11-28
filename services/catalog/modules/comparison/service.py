"""Current public reads only. No retained column is an authority."""
import asyncio
from datetime import datetime, timezone
from typing import Literal, Protocol
from pydantic import AwareDatetime, StrictBool, model_validator
from .contracts import Closed, Column, CompareRequest, Comparison, Facts, Identifier, Revision


class PublicSnapshot(Closed):
    listing_id: Identifier
    watch_id: Identifier
    publication_watch_id: Identifier
    availability_watch_id: Identifier
    organization_id: Identifier | None
    business_id: Identifier | None
    revision: Revision
    availability_revision: Revision
    business_revision: Revision | None
    visibility: Literal['public', 'hidden']
    availability: Literal['available', 'reserved', 'sold', 'removed']
    business_active: StrictBool
    checked_at: AwareDatetime
    valid_until: AwareDatetime
    facts: Facts

    @model_validator(mode='after')
    def current_bindings(self):
        if self.watch_id != self.publication_watch_id or self.watch_id != self.availability_watch_id:
            raise ValueError('Watch binding mismatch')
        if self.organization_id != self.business_id:
            raise ValueError('Business binding mismatch')
        if (self.facts.seller_type == 'private') != (self.organization_id is None):
            raise ValueError('Seller scope mismatch')
        if self.organization_id and self.business_revision is None:
            raise ValueError('Business revision missing')
        if self.valid_until <= self.checked_at:
            raise ValueError('Invalid source validity')
        return self


class PublicProvider(Protocol):
    async def read_public(self, listing_id: str) -> PublicSnapshot | None: ...


async def compare(operation_id: str, request: CompareRequest, provider: PublicProvider | None,
                  clock=lambda: datetime.now(timezone.utc)) -> Comparison:
    columns = []
    validity = {}
    for selected in request.selections:
        base = dict(watch_id=selected.watch_id, expected_revision=selected.expected_revision)
        column = Column(**base, state='pending')
        if provider is not None:
            try:
                async with asyncio.timeout(.75):
                    raw = await provider.read_public(selected.watch_id)
                snapshot = PublicSnapshot.model_validate(raw) if raw is not None else None
                if snapshot is None:
                    column = Column(**base, state='unavailable')
                elif (snapshot.listing_id != selected.watch_id or snapshot.visibility != 'public'
                      or snapshot.availability != 'available' or not snapshot.business_active
                      or not snapshot.checked_at <= clock() < snapshot.valid_until):
                    column = Column(**base, state='unavailable')
                elif selected.expected_revision is not None and selected.expected_revision != snapshot.revision:
                    column = Column(**base, state='stale', revision=snapshot.revision)
                else:
                    column = Column(**base, state='available', revision=snapshot.revision, facts=snapshot.facts)
                    validity[selected.watch_id] = snapshot.valid_until
            except PermissionError:
                column = Column(**base, state='denied')
            except Exception:
                # Dependency bodies and exception text never enter public output.
                column = Column(**base, state='pending')
        columns.append(column)
    finished_at = clock()
    columns = [Column(watch_id=column.watch_id, expected_revision=column.expected_revision, state='unavailable')
               if column.state == 'available' and finished_at >= validity[column.watch_id] else column
               for column in columns]
    return Comparison(operation_id=operation_id, server_time=finished_at, columns=columns)
