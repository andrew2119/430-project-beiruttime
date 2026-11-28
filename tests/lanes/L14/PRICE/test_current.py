import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest
from conftest import load
from bt_contracts.pricing.quotes.current import CurrentQuoteV3, FixedPurchaseCommitV3
from bt_contracts_core.errors import PublicError, AccessDenied

routes = load('price_quotes.current_routes', 'services/pricing/modules/quotes/current_routes.py')
BUYER, ORDER, QUOTE, SOURCE = (UUID(int=i) for i in range(1, 5))
NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)


def preview():
    return dict(quote_id=QUOTE, quote_revision=1, buyer_id=BUYER, source_id=SOURCE,
                source_revision=1, kind='purchase', currency='USD', total_minor=515000,
                expires_at=NOW+timedelta(minutes=15), accepted_at=NOW, schedule_id='usd-v2',
                policy_revision=2, rounding='half_up', status='valid', economics='preview')


def test_preview_and_committed_contracts():
    data = preview()
    assert CurrentQuoteV3(**data).execution_authority == 'not_granted'
    data.update(economics='committed', expires_at=None)
    assert CurrentQuoteV3(**data).total_minor == 515000


@pytest.mark.parametrize('change', [dict(expires_at=None), dict(economics='committed'),
    dict(economics='committed', expires_at=None, accepted_at=None),
    dict(kind='repair'), dict(schedule_id='usd-job-v2'), dict(total_minor=True),
    dict(execution_authority='granted'), dict(currency='LBP')])
def test_inconsistent_authority_denied(change):
    with pytest.raises(ValueError):
        CurrentQuoteV3(**(preview() | change))


def test_commit_delayed_reply_duplicate_conflict_and_recovery(monkeypatch):
    body = FixedPurchaseCommitV3(buyer_id=BUYER, order_id=ORDER, quote_revision=1,
                               total_minor=515000, committed_at=NOW+timedelta(minutes=1))
    row = dict(snapshot={'currency':'USD', 'source':'listing', 'source_verified':True,
                        'purpose':'purchase', 'revision':1, 'payable_minor':515000},
               reviewed_at=NOW, expires_at=NOW+timedelta(minutes=15))
    saved = []
    events = []
    class Connection:
        async def fetchrow(self, sql, *args):
            if 'l14_quote_commitments' in sql:
                return saved[0] if saved else None
            return row if args[1] == BUYER else None
        async def fetchval(self, *args):
            return NOW+timedelta(days=1)
        async def execute(self, *args):
            saved.append(body.model_dump())
    @asynccontextmanager
    async def transaction(*args, **kwargs):
        yield Connection()
    async def enqueue(*args):
        events.append(args[1])
    monkeypatch.setattr(routes, 'unit_of_work', transaction)
    monkeypatch.setattr(routes, 'enqueue', enqueue)
    monkeypatch.setattr(routes.peers, 'service', lambda *args: 'orders')
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=None)),
                              state=SimpleNamespace(request_id='price-recovery'))
    # Allocation was in the preview window; its response arrives the next day.
    asyncio.run(routes.commit(QUOTE, body, request))
    result = asyncio.run(routes.commit(QUOTE, body, request))
    assert result['expires_at'] is None and len(saved) == len(events) == 1
    for update in ({'order_id': UUID(int=99)}, {'total_minor':515001}, {'quote_revision':2},
                   {'committed_at':NOW+timedelta(minutes=2)}):
        with pytest.raises(PublicError) as failure:
            asyncio.run(routes.commit(QUOTE, body.model_copy(update=update), request))
        assert failure.value.code == 'commitment_conflict'
    saved.clear()
    for update in ({'quote_revision':2}, {'total_minor':500000},
                   {'committed_at':NOW+timedelta(minutes=15)}, {'committed_at':NOW-timedelta(seconds=1)}):
        with pytest.raises(PublicError):
            asyncio.run(routes.commit(QUOTE, body.model_copy(update=update), request))
    with pytest.raises(PublicError):
        asyncio.run(routes.commit(QUOTE, body.model_copy(update={'buyer_id':UUID(int=99)}), request))
    def denied(*args):
        raise AccessDenied('Consumer denied')
    monkeypatch.setattr(routes.peers, 'service', denied)
    with pytest.raises(AccessDenied):
        asyncio.run(routes.commit(QUOTE, body, request))


def test_deterministic_recovery_fixtures():
    import json
    from conftest import ROOT
    data = json.loads((ROOT / 'packages/contracts-pricing/quotes/fixtures/current-v3-recovery.json').read_text())
    assert CurrentQuoteV3(**data['preview']).economics == 'preview'
    assert CurrentQuoteV3(**data['committed']).expires_at is None
    assert data['lost_response']['retry'] == data['commit']
    assert FixedPurchaseCommitV3(**data['commit']).total_minor == 515000


def test_retained_job_single_fee_and_exact_half_up():
    from bt_contracts.pricing.quotes.current import RetainedFinancialQuote
    base = dict(quote_id=QUOTE, quote_revision=1, buyer_id=BUYER, source_id=SOURCE,
        source_revision=1, currency='USD', price_minor=10, buyer_fee_minor=0,
        seller_commission_minor=1, seller_net_minor=9, shipping_minor=0, tax_minor=0,
        payable_minor=10, schedule_id='usd-job-v2', policy_revision=2, rounding='half_up',
        minor_unit_exponent=2, sample=True, policy={}, expires_at=None, reviewed_at=NOW,
        authority='retained_read_only')
    assert RetainedFinancialQuote(**base).seller_commission_minor == 1
    for update in ({'seller_commission_minor':0,'seller_net_minor':10},
                   {'buyer_fee_minor':1,'payable_minor':11}):
        with pytest.raises(ValueError):
            RetainedFinancialQuote(**(base | update))
    large = base | dict(price_minor=500000, seller_commission_minor=25000,
                        seller_net_minor=475000, payable_minor=500000)
    assert RetainedFinancialQuote(**large).payable_minor == 500000
    watch = large | dict(schedule_id='usd-v2',buyer_fee_minor=15000,payable_minor=515000)
    assert RetainedFinancialQuote(**watch).payable_minor == 515000
