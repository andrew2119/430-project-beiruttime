"""Lifespan-owned, bounded worker supervision and shutdown."""
import asyncio
import logging
from typing import Awaitable, Callable

logger = logging.getLogger('beirut_time')


class LoopSupervisor:
    def __init__(self, app, workers: dict[str, Callable[..., Awaitable[None]]]):
        if len(workers) > 8:
            raise ValueError('A runtime may register at most eight bounded workers')
        self.app, self.workers = app, workers
        self.stop = asyncio.Event()
        self.tasks: list[asyncio.Task] = []

    async def _run(self, name, callback):
        delay = .5
        while not self.stop.is_set():
            try:
                await callback(self.app, self.stop)
                if self.stop.is_set():
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error('worker.failed', extra={'fields': {'worker': name}})
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=delay)
            except TimeoutError:
                delay = min(delay * 2, 30)

    def start(self):
        self.tasks = [asyncio.create_task(self._run(name, callback), name=name) for name, callback in self.workers.items()]

    async def close(self):
        self.stop.set()
        if self.tasks:
            _, pending = await asyncio.wait(self.tasks, timeout=5)
            for task in pending:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
