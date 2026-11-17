"""Read the canonical public view and current availability in the catalog boundary."""
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt
from uuid import UUID
from ..discovery.search import UNAVAILABLE_SOURCE
from ..discovery.source_contract import SOURCE, COLUMNS, parse_row
from ..discovery.service import resolve, title


class SellerScope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    listing_id: UUID
    seller_id: UUID
    listing_revision: StrictInt
    eligible: StrictBool


class PublicProvider:
    def __init__(self, pool, reads, seller_scope=None):
        self.pool = pool
        self.reads = reads
        self.seller_scope = seller_scope

    async def current_public(self):
        try:
            return await self._read()
        except UNAVAILABLE_SOURCE:
            raise OSError("Current public source unavailable") from None

    async def _read(self):
        async with self.pool.acquire(timeout=.2) as connection:
            rows = await connection.fetch(f'SELECT {COLUMNS} FROM {SOURCE} WHERE published_at<=clock_timestamp() ORDER BY id LIMIT 1002')
        if len(rows) > 1001:
            raise ValueError('Complete public set unavailable')
        sources = [parse_row(row) for row in rows]
        permitted = []
        for source in sources:
            if source.seller_type == 'private':
                if self.seller_scope is None:
                    raise ValueError('Current seller scope unavailable')
                scope = SellerScope.model_validate(await self.seller_scope(source))
                if (scope.listing_id, scope.seller_id, scope.listing_revision) != (source.id, source.seller_id, source.revision):
                    raise ValueError('Current seller scope binding changed')
                if not scope.eligible:
                    continue
            permitted.append(source)
        sources = permitted
        output = []
        cache = {}
        for start in range(0, len(sources), 4):
            batch = sources[start:start + 4]
            ids = [source.id for source in batch if source.facts.sale_mode == 'auction']
            timings, missing = await self.reads.timing_batch(ids)
            current = await resolve(batch, self.reads, timings, missing, cache)
            for item in current:
                if not item.authority_known:
                    raise ValueError('Current public authority unavailable')
                business = item.business
                if business and (business.state != 'active' or not business.platform_onboarded or not business.authenticated_business or 'sales' not in business.capabilities):
                    continue
                source = item.source
                output.append(dict(id=source.id, watch_id=source.physical_watch_id, revision=source.revision,
                                   title=title(source), brand=source.facts.brand, reference=source.facts.reference,
                                   price_minor=source.facts.price_minor, currency=source.facts.currency,
                                   sample=source.is_demo, available=item.state == 'available'))
        return output
