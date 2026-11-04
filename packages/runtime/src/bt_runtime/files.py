"""Private storage seam: authorization precedes metadata/bytes, never a public bucket."""
from typing import Awaitable, Callable, Protocol
from uuid import UUID
from .principal import CurrentPrincipal


class PrivateStore(Protocol):
    async def read(self, blob_id: UUID, *, max_bytes: int) -> bytes: ...


class ScopedFiles:
    def __init__(self, store: PrivateStore,
                 authorize: Callable[[CurrentPrincipal, UUID], Awaitable[UUID]], max_bytes: int = 10 * 1024 * 1024):
        if max_bytes < 1:
            raise ValueError('File budget must be positive')
        self.store, self.authorize, self.max_bytes = store, authorize, max_bytes

    async def read(self, principal: CurrentPrincipal, resource_id: UUID) -> bytes:
        # The domain maps its authorized resource to an opaque blob id. No supplied paths.
        blob_id = await self.authorize(principal, resource_id)
        content = await self.store.read(blob_id, max_bytes=self.max_bytes)
        if len(content) > self.max_bytes:
            raise ValueError('File exceeds the permitted byte budget')
        return content
