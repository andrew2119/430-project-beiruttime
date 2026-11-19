"""One local transaction retains the request, immutable receipt and safe event."""
import hashlib
from bt_contracts.service.cleaning.v1 import Result
from bt_runtime.app.db import unit_of_work
from bt_events import enqueue
from bt_contracts_core.models import EventEnvelope
from .domain import Denied, decide


def digest(command):
    return hashlib.sha256(command.model_dump_json().encode()).hexdigest()


class Store:
    def __init__(self, pool):
        self.pool = pool

    async def read(self, subject):
        async with self.pool.acquire(timeout=1) as tx:
            raw = await tx.fetchval('SELECT result FROM l21_cleaning_requests WHERE subject_id=$1', subject)
        return Result.model_validate_json(raw) if raw else None

    async def lookup(self, operation, actor, subject):
        async with self.pool.acquire(timeout=1) as tx:
            raw = await tx.fetchval('''SELECT result FROM l21_cleaning_receipts
                WHERE operation_id=$1 AND actor_id=$2 AND subject_id=$3''', operation, actor, subject)
        return Result.model_validate_json(raw) if raw else None

    async def apply(self, command, facts, clock):
        async with unit_of_work(self.pool, lock_key='cleaning:' + str(command.subject_id)) as tx:
            # A second lock serializes reuse across subjects as well.
            await tx.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',
                             'cleaning-operation:' + str(command.operation_id))
            prior = await tx.fetchrow('SELECT * FROM l21_cleaning_receipts WHERE operation_id=$1', command.operation_id)
            if prior:
                if (prior['actor_id'] != command.actor_id or prior['subject_id'] != command.subject_id
                        or prior['request_hash'] != digest(command)):
                    raise Denied('operation_conflict')
                return Result.model_validate_json(prior['result'])
            raw = await tx.fetchval('SELECT result FROM l21_cleaning_requests WHERE subject_id=$1 FOR UPDATE',
                                    command.subject_id)
            result = decide(command, Result.model_validate_json(raw) if raw else None, facts, clock())
            encoded = result.model_dump_json()
            await tx.execute('''INSERT INTO l21_cleaning_requests(subject_id,result) VALUES($1,$2::jsonb)
                ON CONFLICT(subject_id) DO UPDATE SET result=EXCLUDED.result''', command.subject_id, encoded)
            await tx.execute('''INSERT INTO l21_cleaning_receipts(operation_id,actor_id,subject_id,request_hash,result)
                VALUES($1,$2,$3,$4,$5::jsonb)''', command.operation_id, command.actor_id,
                command.subject_id, digest(command), encoded)
            event = {'schema_version': 'cleaning.v1', 'operation_id': str(command.operation_id),
                     'subject_id': str(command.subject_id), 'organization_id': str(command.organization_id),
                     'revision': result.revision, 'state': result.state}
            await enqueue(tx, EventEnvelope(type='service-operations.cleaning.recorded.v1',
                          source='service-operations', subject=str(command.subject_id),
                          request_id=str(command.operation_id), data=event), ['communications'])
            return result
