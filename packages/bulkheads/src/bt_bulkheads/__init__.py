"""Dependency-owned budgets, no hidden retries or fallback business successes."""
import asyncio
import time
from dataclasses import dataclass
from typing import Literal
import httpx


@dataclass(frozen=True)
class Unavailable:
    dependency: str
    reason: Literal['timeout', 'saturated', 'circuit_open', 'network', 'upstream']
    retry_after: float = 1.0


class DependencyClient:
    """One instance per dependency per process. Saturation sheds, never queues.

    Half-open allows exactly one probe. HTTP 4xx are domain responses, not outages.
    The invocation deadline includes body loading. Callers own response validation.
    """
    def __init__(self, dependency: str, base_url: str, *, timeout: float = 1.5,
                 concurrency: int = 8, failure_threshold: int = 3,
                 cooldown: float = 10, transport: httpx.AsyncBaseTransport | None = None):
        if concurrency < 1 or timeout <= 0 or failure_threshold < 1 or cooldown <= 0:
            raise ValueError('Budgets must be positive')
        self.dependency = dependency
        self.timeout = timeout
        self.concurrency = concurrency
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown
        self._active = 0
        self._failures = 0
        self._opened_at: float | None = None
        self._probe = False
        self.client = httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(timeout, connect=min(.3, timeout)),
            limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
            transport=transport, follow_redirects=False)

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response | Unavailable:
        if not path.startswith('/') or path.startswith('//') or httpx.URL(path).is_absolute_url:
            raise ValueError('Dependency paths must be relative to the registered origin')
        now = time.monotonic()
        half_open = self._opened_at is not None
        if half_open and (now - self._opened_at < self.cooldown or self._probe):
            return Unavailable(self.dependency, 'circuit_open', self.cooldown)
        # No await between admission and increment: atomic within this event loop.
        if self._active >= self.concurrency:
            return Unavailable(self.dependency, 'saturated')
        self._active += 1
        if half_open:
            self._probe = True
        failed = True
        try:
            async with asyncio.timeout(self.timeout):
                async with self.client.stream(method, path, **kwargs) as upstream:
                    chunks, size = [], 0
                    async for chunk in upstream.aiter_bytes():
                        size += len(chunk)
                        if size > 2 * 1024 * 1024:
                            return Unavailable(self.dependency, 'upstream')
                        chunks.append(chunk)
                    headers = {key: value for key, value in upstream.headers.items()
                               if key.lower() not in {'content-encoding', 'content-length', 'transfer-encoding'}}
                    response = httpx.Response(upstream.status_code, headers=headers,
                        content=b''.join(chunks), request=upstream.request)
            if response.status_code >= 500 or response.status_code == 429:
                return Unavailable(self.dependency, 'upstream')
            failed = False
            self._failures = 0
            self._opened_at = None
            return response
        except (TimeoutError, httpx.TimeoutException):
            return Unavailable(self.dependency, 'timeout')
        except httpx.HTTPError:
            return Unavailable(self.dependency, 'network')
        except asyncio.CancelledError:
            failed = False
            raise
        finally:
            self._active -= 1
            self._probe = False
            if failed:
                self._failures += 1
                if half_open or self._failures >= self.failure_threshold:
                    self._opened_at = time.monotonic()

    async def aclose(self) -> None:
        await self.client.aclose()
