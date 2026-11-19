"""Unregistered versioned route boundary; the host supplies authenticated context."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from .model import Refused


class Boundary:
    def __init__(self, store_factory):
        self.store_factory = store_factory
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.busy = False

    async def execute(self, command, actor_id, organization_id):
        def envelope(state, code):
            return {**{key: command.get(key) for key in ('operation_id', 'subject_id', 'watch_id', 'actor_id', 'organization_id', 'expected_revision')},
                    'schema_version': 'transaction-reviews.v1', 'state': state, 'code': code, 'revision': None,
                    'pending_reason': code if state == 'pending' else None,
                    'next_actor': actor_id, 'next_review_at': None}

        if command.get('actor_id') != actor_id or command.get('organization_id') != organization_id:
            return envelope('denied', 'scope_denied')
        # A timed-out commit may finish. Its immutable operation is always retried.
        if self.busy:
            return envelope('unavailable', 'capacity_unavailable')
        self.busy = True
        async def run():
            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(self.executor, partial(self._execute, command))
            finally:
                self.busy = False
        task = asyncio.create_task(run())
        task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None)
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=2)
        except TimeoutError:
            return envelope('pending', 'result_unknown')
        except (OSError, ValueError, TypeError, KeyError) as error:
            code = str(error) if isinstance(error, Refused) else 'unavailable'
            return envelope('stale' if code == 'stale_revision' else 'unavailable' if code == 'unavailable' else 'denied', code)

    def _execute(self, command):
        store = self.store_factory()
        try:
            return store.command(command)
        finally:
            store.db.close()
