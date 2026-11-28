"""Current quote writes and lossless legacy reconciliation across the binding upgrade."""
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import asyncpg
import pytest
from bt_contracts.pricing.quotes.models import QuoteRequest, QuoteReview, QuoteSnapshot
from bt_contracts_core.errors import PublicError
from modules.quotes import current_routes, retained, routes

MODULE = Path(__file__).resolve().parents[1]


async def insert(conn, snapshot, *, archived=False):
    columns = ',archived' if archived else ''
    values = ',true' if archived else ''
    await conn.execute(f'''INSERT INTO l07_quotes
        (id,owner_id,idempotency_key,request_hash,snapshot,created_at,expires_at{columns})
        VALUES($1,$2,$3,$4,$5::jsonb,$6,$7{values})''',
        UUID(snapshot['id']), UUID(snapshot['owner_id']), 'test-' + snapshot['id'],
        'test-request-hash', json.dumps(snapshot), datetime.fromisoformat(snapshot['created_at']),
        datetime.fromisoformat(snapshot['expires_at']))


def legacy_quote(owner, currency, *, purchase=False):
    # Original sample-v1 writer omitted policy revision and stored review time
    # separately. The LBP amount is in its original denomination.
    return {'id': str(uuid4()), 'owner_id': str(owner), 'subject_id': str(uuid4()), 'subject_revision': 7,
            'purpose': 'purchase' if purchase else 'business_quote', 'source': 'listing' if purchase else 'sample',
            'source_verified': purchase, 'currency': currency, 'schedule_id': 'sample-v1', 'revision': 1,
            'price_minor': 10001, 'buyer_fee_minor': 300, 'seller_commission_minor': 500,
            'seller_net_minor': 9501, 'shipping_minor': 0, 'tax_minor': 0, 'payable_minor': 10301,
            'minor_unit_exponent': 2, 'sample': True, 'rounding': 'half_up', 'fx': None,
            'commission_basis': 'price_excluding_buyer_fee_shipping_tax',
            'policy': {'buyer_fee_bps': 300, 'seller_commission_bps': 500, 'shipping': 'sample_zero',
                       'tax': 'sample_zero', 'fx': 'not_applied', 'currency_exponents': {'USD': 2, 'LBP': 2}},
            'created_at': '2026-11-16T08:00:00+00:00', 'expires_at': '2026-11-16T08:15:00+00:00',
            'reviewed_at': None}


@pytest.mark.asyncio
@pytest.mark.parametrize('database_access', ['core-only'], indirect=True)
async def test_upgrade_archives_history_and_accepts_current_quote(database_owner_url, database_url, monkeypatch):
    owner = uuid4()
    lbp, usd = legacy_quote(owner, 'LBP'), legacy_quote(owner, 'USD', purchase=True)
    offer = {**legacy_quote(owner, 'USD'), 'purpose': 'offer'}
    lbp_id, usd_id, offer_id = (UUID(snapshot['id']) for snapshot in (lbp, usd, offer))
    historical = {lbp_id: lbp, usd_id: usd, offer_id: offer}
    body = QuoteRequest(subject_id=lbp['subject_id'], subject_revision=lbp['subject_revision'],
                        purpose='purchase', source='sample', currency='USD', schedule_id='usd-v2', price_minor=10001)
    review = QuoteReview(**body.model_dump(), quote_revision=1, payable_minor=10301)
    when = datetime.fromisoformat('2026-11-16T08:05:00+00:00')
    before_sql = 'SELECT to_jsonb(q) - $2::text FROM l07_quotes q WHERE id=$1'
    conn = await asyncpg.connect(database_owner_url)
    try:
        migrations = json.loads((MODULE / 'module.json').read_text())['migrations']
        for migration in migrations[:-1]:
            await conn.execute((MODULE / migration).read_text())
        for snapshot in historical.values():
            await insert(conn, snapshot)
        await conn.execute('UPDATE l07_quotes SET reviewed_at=$2 WHERE id=$1', usd_id, when)
        await conn.execute('INSERT INTO l07_quote_reviews VALUES($1,$2,$3,$4,$5)',
                           usd_id, owner, 'old-review', 'old-review-hash', when)
        before = {quote_id: await conn.fetchval(before_sql, quote_id, 'archived') for quote_id in historical}
        stored_review = await conn.fetchrow('SELECT * FROM l07_quote_reviews WHERE quote_id=$1', usd_id)
        # Keep historical foreign keys in place across the same upgrade.
        for directory in (MODULE / 'current-state', MODULE.parent / 'offers'):
            for migration in sorted((directory / 'migrations').glob('*.sql')):
                await conn.execute(migration.read_text())
        order = uuid4()
        await conn.execute("INSERT INTO l14_quote_commitments VALUES($1,$2,$3,1,'USD',10301,$4)",
                           usd_id, owner, order, when)
        await conn.execute('''INSERT INTO l14_offers
            (id,listing_id,listing_revision,watch_id,buyer_id,seller_id,quote_id,snapshot,state,expires_at,accepted_at,accepted_revision)
            VALUES($1,$2,7,$3,$4,$5,$6,$7::jsonb,'accepted',$8,$9,2)''',
            uuid4(), UUID(offer['subject_id']), uuid4(), owner, uuid4(), offer_id, json.dumps(offer),
            datetime.fromisoformat('2026-11-18T08:00:00+00:00'), when)
        commitment = await conn.fetchrow('SELECT * FROM l14_quote_commitments WHERE quote_id=$1', usd_id)
        stored_offer = await conn.fetchrow('SELECT * FROM l14_offers WHERE quote_id=$1', offer_id)
        await conn.execute((MODULE / migrations[-1]).read_text())
        for quote_id, snapshot in historical.items():
            assert await conn.fetchval('SELECT archived FROM l07_quotes WHERE id=$1', quote_id) is True
            stored = await conn.fetchval(before_sql, quote_id, 'archived')
            assert stored == before[quote_id]
            assert json.loads(stored)['snapshot'] == snapshot
        assert await conn.fetchrow('SELECT * FROM l07_quote_reviews WHERE quote_id=$1', usd_id) == stored_review
        assert await conn.fetchrow('SELECT * FROM l14_quote_commitments WHERE quote_id=$1', usd_id) == commitment
        assert await conn.fetchrow('SELECT * FROM l14_offers WHERE quote_id=$1', offer_id) == stored_offer
        with pytest.raises(asyncpg.RaiseError, match='immutable'):
            await conn.execute('UPDATE l07_quotes SET archived=false WHERE id=$1', usd_id)
        with pytest.raises(asyncpg.RaiseError, match='cannot be deleted'):
            await conn.execute('DELETE FROM l07_quotes WHERE id=$1', lbp_id)
        assert await conn.fetchval("SELECT convalidated FROM pg_constraint WHERE conname='l07_quote_snapshot_binding'")

        async with asyncpg.create_pool(database_url, min_size=1, max_size=1) as pool:
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=pool)),
                                      state=SimpleNamespace(request_id=str(uuid4())))
            assert await pool.fetchval('SELECT count(*) FROM l07_quotes') == 0
            assert await pool.fetchval('SELECT count(*) FROM l07_quote_reviews') == 0
            assert await routes.list_quotes(request, owner, page=1, page_size=30) == {
                'items': [], 'total': 0, 'page': 1, 'page_size': 30}
            for quote_id in historical:
                for endpoint, args in ((routes.read, (quote_id, request, owner)),
                                       (routes.review, (quote_id, review, request, owner, 'new-review')),
                                       (routes.validate_for_reservation, (quote_id, request, owner))):
                    with pytest.raises(PublicError, match='not_found') as error:
                        await endpoint(*args)
                    assert error.value.status == 404
            monkeypatch.setattr(current_routes.peers, 'service', lambda *_: 'orders')
            for read in (retained.retained, current_routes.validation):
                for quote_id in (usd_id, offer_id):
                    with pytest.raises(PublicError, match='legacy_reconciliation') as error:
                        await read(quote_id, owner, request)
                    assert error.value.status == 409
                for quote_id, buyer in ((usd_id, uuid4()), (lbp_id, owner)):
                    with pytest.raises(PublicError, match='not_found'):
                        await read(quote_id, buyer, request)

            with pytest.raises(PublicError, match='idempotency_conflict'):
                await routes.create(body, request, owner, 'test-' + lbp['id'])
            snapshot = await routes.create(body, request, owner, 'new-current-quote')
            assert QuoteSnapshot.model_validate(snapshot).schedule_id == 'usd-v2'
            assert snapshot['currency'] == 'USD' and snapshot['policy']['revision'] == 2
            assert await routes.create(body, request, owner, 'new-current-quote') == snapshot
            active_id = UUID(snapshot['id'])
            assert await routes.read(active_id, request, owner) == snapshot
            history = await routes.list_quotes(request, owner, page=1, page_size=30)
            assert history['total'] == 1 and [row['id'] for row in history['items']] == [snapshot['id']]
            with pytest.raises(PublicError, match='idempotency_conflict'):
                await routes.review(active_id, review, request, owner, 'old-review')
            accepted = await routes.review(active_id, review, request, owner, 'new-review')
            assert accepted['reviewed_at']
            assert await routes.review(active_id, review, request, owner, 'new-review') == accepted

            for fields in ({'currency': 'LBP'}, {'schedule_id': 'sample-v1'}, {'sample': False},
                           {'revision': 2}, {'minor_unit_exponent': 3},
                           {'payable_minor': 1}, {'seller_net_minor': 1}, {'shipping_minor': 1}):
                with pytest.raises(asyncpg.CheckViolationError):
                    await insert(pool, {**snapshot, 'id': str(uuid4()), **fields})
            with pytest.raises(asyncpg.RaiseError, match='must be active'):
                await insert(pool, {**lbp, 'id': str(uuid4())}, archived=True)
            with pytest.raises(asyncpg.RaiseError, match='immutable'):
                await pool.execute("UPDATE l07_quotes SET snapshot=snapshot || '{\"sample\":false}'::jsonb WHERE id=$1",
                                   active_id)
    finally:
        await conn.close()
