"""Serialized service-owned persistence for the version-one factor contract."""
import asyncio

from .core import FactorEngine, Rejected, authorize


class Repository:
    def __init__(self, pool, key, current_authority, clock):
        if len(key) != 32:
            raise ValueError('key_length')
        self.pool, self.current_authority, self.clock = pool, current_authority, clock
        self.engine = FactorEngine(key)

    async def authority(self, command):
        try:
            async with asyncio.timeout(2):
                authority = await self.current_authority(command)
        except Exception:
            raise Rejected('unavailable') from None
        # Apply the same identity admission to every private read and retry.
        return authorize(command, authority)

    async def lookup(self, command):
        try:
            async with asyncio.timeout(4):
                return await self._lookup(command)
        except TimeoutError:
            raise Rejected('unavailable') from None

    async def _lookup(self, command):
        authority = await self.authority(command)
        async with self.pool.acquire() as tx:
            row = await tx.fetchrow('''SELECT o.result,f.data FROM identity_l19_factor_operations o
                JOIN identity_l19_factors f ON o.subject_id=f.subject_id
                WHERE o.subject_id=$1 AND o.operation_id=$2''', command.subject_id, command.operation_id)
        if not row:
            raise Rejected('unavailable')
        return self.engine.read_receipt(command, row['result'],
                                        self.engine.open(command.subject_id, row['data']), authority)

    async def execute(self, command):
        try:
            async with asyncio.timeout(4):
                return await self._execute(command)
        except TimeoutError:
            raise Rejected('unavailable') from None

    async def committed(self, command, authority):
        async with self.pool.acquire() as tx:
            row = await tx.fetchrow('''SELECT o.digest,o.result,f.data FROM identity_l19_factor_operations o
                JOIN identity_l19_factors f ON o.subject_id=f.subject_id
                WHERE o.subject_id=$1 AND o.operation_id=$2''', command.subject_id, command.operation_id)
        if row is None:
            return None
        if row['digest'] != self.engine.digest(command.model_dump_json()):
            raise Rejected('conflict')
        return self.engine.read_receipt(command, row['result'],
                                        self.engine.open(command.subject_id, row['data']), authority)

    async def _execute(self, command):
        authority = await self.authority(command)
        prior = await self.committed(command, authority)
        if prior is not None:
            return prior
        subject, now = command.subject_id, int(self.clock())
        # Durable failed-attempt admission is independent of transition rollback.
        async with self.pool.acquire() as tx:
            count = await tx.fetchval('''INSERT INTO identity_l19_factor_limits(subject_id,window_at,attempts)
                VALUES($1,$2,1) ON CONFLICT(subject_id) DO UPDATE SET
                attempts=CASE WHEN identity_l19_factor_limits.window_at+300<=$2 THEN 1
                    ELSE identity_l19_factor_limits.attempts+1 END,
                window_at=CASE WHEN identity_l19_factor_limits.window_at+300<=$2 THEN $2
                    ELSE identity_l19_factor_limits.window_at END RETURNING attempts''', subject, now)
        if count > 10:
            raise Rejected('try_later')
        async with self.pool.acquire() as tx:
            async with tx.transaction():
                await tx.execute("SET LOCAL lock_timeout = '2s'")
                await tx.execute("SET LOCAL statement_timeout = '2s'")
                initial = {'revision': 0, 'status': 'empty', 'proofs': {}}
                await tx.execute('''INSERT INTO identity_l19_factors(subject_id,data) VALUES($1,$2)
                    ON CONFLICT DO NOTHING''', subject, self.engine.seal(subject, initial))
                row = await tx.fetchrow('SELECT data FROM identity_l19_factors WHERE subject_id=$1 FOR UPDATE', subject)
                authority = await self.authority(command)
                now = int(self.clock())
                prior = await tx.fetchrow('''SELECT digest,result FROM identity_l19_factor_operations
                    WHERE subject_id=$1 AND operation_id=$2''', subject, command.operation_id)
                digest = self.engine.digest(command.model_dump_json())
                state = self.engine.open(subject, row['data'])
                if prior:
                    if prior['digest'] != digest:
                        raise Rejected('conflict')
                    return self.engine.read_receipt(command, prior['result'], state, authority)
                if state['revision'] != command.expected_revision:
                    raise Rejected('stale_revision')
                result = self.engine.apply(command, authority, state, now)
                state['revision'] += 1
                result.update(schema_version=1, operation_id=command.operation_id, subject_id=subject,
                              actor_id=command.actor_id, watch_id=None, organization_id=command.organization_id,
                              expected_revision=command.expected_revision, revision=state['revision'],
                              pending_reason='session_revocation' if state['status'] == 'pending' else None,
                              next_actor='identity' if state['status'] == 'pending' else None,
                              next_review_at=self.engine.instant(now + 86400) if state['status'] == 'pending' else None)
                await tx.execute('UPDATE identity_l19_factors SET data=$2 WHERE subject_id=$1',
                                 subject, self.engine.seal(subject, state))
                await tx.execute('''INSERT INTO identity_l19_factor_operations
                    (subject_id,operation_id,digest,result) VALUES($1,$2,$3,$4)''',
                                 subject, command.operation_id, digest, self.engine.seal(subject, self.engine.receipt(state, authority, result, command)))
                if command.kind == 'recover':
                    await tx.execute('''INSERT INTO identity_l19_factor_outbox
                        (operation_id,subject_id,kind) VALUES($1,$2,'revoke_sessions')''',
                                     command.operation_id, subject)
                if command.kind == 'revoke_ack':
                    await tx.execute('''UPDATE identity_l19_factor_outbox SET acknowledged=true
                        WHERE operation_id=$1 AND subject_id=$2''', command.proof_id, subject)
                return result
