"""Current quote writes and retained history across the binding upgrade."""
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from bt_contracts.pricing.quotes.models import QuoteRequest, QuoteSnapshot

MODULE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('quote_calculation', MODULE / 'calculation.py')
calculation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(calculation)


async def insert(conn, snapshot):
    await conn.execute('''INSERT INTO l07_quotes
        (id,owner_id,idempotency_key,request_hash,snapshot,created_at,expires_at)
        VALUES($1,$2,$3,$4,$5::jsonb,$6,$7)''',
        UUID(snapshot['id']), UUID(snapshot['owner_id']), 'test-' + snapshot['id'],
        'test-request-hash', json.dumps(snapshot), datetime.fromisoformat(snapshot['created_at']),
        datetime.fromisoformat(snapshot['expires_at']))


def current_quote():
    return calculation.calculate(QuoteRequest(
        subject_id=uuid4(), subject_revision=1, purpose='purchase', currency='USD',
        price_minor=10001, schedule_id='usd-v2', source='listing'), uuid4(), source_verified=True)


@pytest.mark.asyncio
@pytest.mark.parametrize('database_access', ['core-only'], indirect=True)
async def test_upgrade_migrates_history_and_accepts_current_quote(database_owner_url):
    conn = await asyncpg.connect(database_owner_url)
    try:
        migrations = json.loads((MODULE / 'module.json').read_text())['migrations']
        for migration in migrations[:-1]:
            await conn.execute((MODULE / migration).read_text())
        historical = []
        for currency in ('USD', 'LBP'):
            snapshot = {**current_quote(), 'currency': currency, 'schedule_id': 'sample-v1'}
            await insert(conn, snapshot)
            historical.append(snapshot)
        await conn.execute((MODULE / migrations[-1]).read_text())
        for snapshot in historical:
            stored = await conn.fetchval('SELECT snapshot FROM l07_quotes WHERE id=$1', UUID(snapshot['id']))
            expected = {**snapshot, 'currency': 'USD', 'schedule_id': 'usd-v2'}
            assert json.loads(stored) == expected
            QuoteSnapshot.model_validate(expected)
            await conn.execute('UPDATE l07_quotes SET reviewed_at=now() WHERE id=$1', UUID(snapshot['id']))
            with pytest.raises(asyncpg.RaiseError, match='immutable'):
                await conn.execute("UPDATE l07_quotes SET snapshot=snapshot || '{\"price_minor\":1}'::jsonb WHERE id=$1",
                                   UUID(snapshot['id']))
        assert await conn.fetchval("SELECT convalidated FROM pg_constraint WHERE conname='l07_quote_snapshot_binding'")
        snapshot = current_quote()
        QuoteSnapshot.model_validate(snapshot)
        await insert(conn, snapshot)
        for fields in ({'currency': 'LBP'}, {'schedule_id': 'sample-v1'}, {'sample': False},
                       {'revision': 2}, {'minor_unit_exponent': 3},
                       {'payable_minor': 1}, {'seller_net_minor': 1}, {'shipping_minor': 1}):
            invalid = {**current_quote(), **fields}
            with pytest.raises(asyncpg.CheckViolationError):
                await insert(conn, invalid)
        with pytest.raises(asyncpg.RaiseError, match='immutable'):
            await conn.execute("UPDATE l07_quotes SET snapshot=snapshot || '{\"sample\":false}'::jsonb WHERE id=$1",
                               UUID(snapshot['id']))
    finally:
        await conn.close()
