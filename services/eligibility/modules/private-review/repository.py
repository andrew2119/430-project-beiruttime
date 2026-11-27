"""Atomic local storage; the shared outbox owns delivery and retry."""
import json
from contextlib import asynccontextmanager
from uuid import UUID
from bt_contracts_core.models import EventEnvelope
from bt_events import enqueue
from bt_runtime.app.db import unit_of_work


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


class Transaction:
    def __init__(self, connection, case_id, request_id):
        self.connection, self.case_id, self.request_id = connection, case_id, request_id

    async def load(self):
        value = await self.connection.fetchval('SELECT snapshot FROM l20_private_review_cases WHERE case_id=$1 FOR UPDATE', self.case_id)
        return decoded(value) if value is not None else None

    async def receipt(self, operation_id):
        row = await self.connection.fetchrow('SELECT actor_id,digest,result FROM l20_private_review_receipts WHERE case_id=$1 AND operation_id=$2', self.case_id, operation_id)
        return {'actor_id': str(row['actor_id']), 'digest': row['digest'], 'result': decoded(row['result'])} if row else None

    async def save(self, case):
        await self.connection.execute('''INSERT INTO l20_private_review_cases(case_id,snapshot) VALUES($1,$2::jsonb)
            ON CONFLICT(case_id) DO UPDATE SET snapshot=EXCLUDED.snapshot''', self.case_id, json.dumps(case))

    async def audit(self, actor_id, action, clock):
        await self.connection.execute('INSERT INTO l20_private_review_audit(case_id,actor_id,action,recorded_at) VALUES($1,$2,$3,$4)', self.case_id, UUID(actor_id), action, clock)

    async def record(self, operation_id, actor_id, digest, result):
        await self.connection.execute('INSERT INTO l20_private_review_receipts VALUES($1,$2,$3,$4,$5::jsonb)', self.case_id, operation_id, UUID(actor_id), digest, json.dumps(result))
        await self.connection.execute('INSERT INTO l20_private_review_audit(case_id,actor_id,action) VALUES($1,$2,$3)', self.case_id, UUID(actor_id), 'command')

    async def emit(self, event):
        await enqueue(self.connection, EventEnvelope(type='eligibility.private-review-changed.v1', source='eligibility',
            subject=str(self.case_id), request_id=self.request_id, data=event), ['catalog'])


class Repository:
    def __init__(self, pool, request_id):
        self.pool, self.request_id = pool, request_id

    @asynccontextmanager
    async def transaction(self, case_id):
        async with unit_of_work(self.pool, lock_key='private-review:' + str(case_id)) as connection:
            yield Transaction(connection, case_id, self.request_id)
