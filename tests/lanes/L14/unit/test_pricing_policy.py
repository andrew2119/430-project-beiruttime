import asyncio
import importlib
import sys
import types
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from uuid import UUID
import pytest
from conftest import load, ROOT
from bt_contracts.pricing.quotes.assessed import IssueQuote, AcceptQuote
from bt_contracts.pricing.quotes.models import QuoteRequest
from bt_contracts.pricing.quotes.current import CurrentQuoteV3
from bt_contracts_core.errors import PublicError, AccessDenied
from bt_runtime.principal import CurrentPrincipal

for name, relative in [('service_app', 'services/pricing/runtime/service_app'),
                       ('l14quotes', 'services/pricing/modules/quotes')]:
    module = types.ModuleType(name)
    module.__path__ = [str(ROOT / relative)]
    sys.modules[name] = module
current = load('service_app.current', 'services/pricing/runtime/service_app/current.py')
assessed = load('service_app.assessed', 'services/pricing/runtime/service_app/assessed.py')
routes = load('l14quotes.current_routes', 'services/pricing/modules/quotes/current_routes.py')
calculation = load('l14quotes.calculation', 'services/pricing/modules/quotes/calculation.py')
BUYER, ORG, SOURCE, ASSESSMENT, LINE, QUOTE = (UUID(int=i) for i in range(10, 16))
NOW = datetime.now(timezone.utc)


def snapshot():
    return {'id': str(QUOTE), 'revision': 1, 'source_id': str(SOURCE), 'source_revision': 1,
            'assessment_id': str(ASSESSMENT), 'assessment_revision': 1, 'buyer_id': str(BUYER),
            'currency': 'USD', 'schedule_id': 'usd-job-v2', 'policy': current.JOB_POLICY,
            'terms_digest': 'a' * 64, 'lines': [{'id': str(LINE), 'label': 'Accepted parts', 'kind': 'part',
            'mandatory': True, 'amount_minor': 500000, 'part_reference': None}],
            'assessment_fee_minor': 0, 'return_fee_minor': 1000}


def test_watch_rates_and_business_only_job_fee_half_up():
    totals = current.amounts(snapshot()['lines'], [str(LINE)], 0)
    assert totals['payable_minor'] == 500000
    assert totals['platform_fee_minor'] == totals['seller_commission_minor'] == 25000
    assert totals['seller_net_minor'] == 475000
    assert current.JOB_POLICY['fee_deducted_from_customer_refund'] is False
    assert current.JOB_POLICY['full_refund_fee_funding'] == 'business_saved_simulated_method'
    assert current.percentage(10, 500) == 1
    request = QuoteRequest(subject_id=SOURCE, subject_revision=1, purpose='purchase', currency='USD',
                           price_minor=500000, schedule_id='usd-v2')
    q = calculation.calculate(request, BUYER, NOW)
    assert (q['buyer_fee_minor'], q['seller_commission_minor'], q['payable_minor']) == (15000, 25000, 515000)
    assert datetime.fromisoformat(q['expires_at']) - NOW == timedelta(minutes=15)


def test_exact_active_money_and_legacy_reconciliation():
    for currency, amount in [('LBP', 100), ('USD', 1.5), ('USD', True)]:
        with pytest.raises(ValueError):
            QuoteRequest(subject_id=SOURCE, subject_revision=1, purpose='offer', currency=currency,
                         price_minor=amount, schedule_id='usd-v2')
    with pytest.raises(PublicError):
        current.require_usd({'currency': 'LBP'})
    with pytest.raises(PublicError):
        current.amounts(snapshot()['lines'], [str(LINE), str(LINE)], 0)


def test_only_customer_and_preview_not_accepted_expiry():
    current.current_time({'state': 'accepted', 'expires_at': NOW - timedelta(days=90)}, NOW)
    with pytest.raises(PublicError):
        current.current_time({'state': 'issued', 'expires_at': NOW}, NOW)
    row = {'buyer_id': BUYER, 'organization_id': ORG}
    buyer = CurrentPrincipal(actor={'subject_id': BUYER, 'session_id': 'unit'}, roles=['buyer'])
    assessed.access(row, buyer)
    other = CurrentPrincipal(actor={'subject_id': UUID(int=99), 'session_id': 'unit'}, roles=['buyer'])
    with pytest.raises(AccessDenied):
        assessed.access(row, other)
    command = AcceptQuote(quote_revision=1, selected_line_ids=[LINE], payable_minor=500000, terms_digest='a'*64)
    assert command.accept_assessment_fee is False and command.accept_return_fee is False
    assert IssueQuote.model_fields['currency'].annotation.__args__ == ('USD',)


class Connection:
    def __init__(self, rows):
        self.rows = rows
    async def fetchrow(self, sql, *args):
        return next((row for table, row in self.rows.items() if 'FROM ' + table + ' ' in sql), None)
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass


def request_for(rows):
    tx = Connection(rows)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=SimpleNamespace(acquire=lambda: tx))))


def test_accepted_job_validation_has_no_old_expiry_and_scope_rechecks(monkeypatch):
    q = snapshot()
    quote = {'id': QUOTE, 'buyer_id': BUYER, 'source_id': SOURCE, 'source_revision': 1, 'kind': 'brand',
             'organization_id': ORG, 'state': 'accepted', 'revision': 1, 'snapshot': q,
             'expires_at': NOW - timedelta(days=30)}
    decision = {'decision': 'accepted', 'decided_at': NOW - timedelta(days=31), 'terms_digest': q['terms_digest'],
                'selected_line_ids': [str(LINE)], 'amounts': current.amounts(q['lines'], [str(LINE)], 0)}
    request = request_for({'l14_assessed_quotes': quote, 'l14_quote_decisions': decision})
    monkeypatch.setattr(routes.peers, 'service', lambda *a: 'eligibility')
    async def source(*args):
        return {'buyer_id': str(BUYER), 'organization_id': str(ORG)}
    monkeypatch.setattr(routes, 'current_source', source)
    result = asyncio.run(routes.validation(QUOTE, BUYER, request))
    validated = CurrentQuoteV3.model_validate(result)
    assert validated.expires_at is None and validated.total_minor == 500000
    assert validated.economics == 'committed' and validated.execution_authority == 'not_granted'
    async def changed(*args):
        raise PublicError('consent_withdrawn', 'Ineffective current consent', status=409)
    monkeypatch.setattr(routes, 'current_source', changed)
    with pytest.raises(PublicError):
        asyncio.run(routes.validation(QUOTE, BUYER, request))
    assert quote['snapshot'] == q  # Current denial never rewrites history.


def test_winner_economics_survive_delayed_allocation_revision(monkeypatch):
    q = {'id': str(QUOTE), 'revision': 1, 'subject_revision': 7, 'currency': 'USD', 'price_minor': 500000,
         'payable_minor': 515000, 'listing_id': str(LINE), 'listing_revision': 1, 'watch_id': str(ASSESSMENT),
         'end_version': 1, 'close_version': 1, 'schedule_id': 'usd-v2', 'policy': current.POLICY}
    auction = {'buyer_id': BUYER, 'auction_id': SOURCE, 'kind': 'winner', 'snapshot': q, 'created_at': NOW,
               'expires_at': NOW - timedelta(days=7)}
    request = request_for({'l14_auction_quotes': auction})
    monkeypatch.setattr(routes.peers, 'service', lambda *a: 'orders')
    auction_routes = importlib.import_module('l14quotes.auction_routes')
    async def source(*args):
        return {**q, 'revision': 9}
    monkeypatch.setattr(auction_routes, 'source', source)
    result = asyncio.run(routes.validation(QUOTE, BUYER, request))
    assert result['source_revision'] == 7 and result['expires_at'] is None


def test_accepted_offer_uses_admission_revision_not_later_receipt_revision(monkeypatch):
    q = {'revision': 1, 'currency': 'USD', 'payable_minor': 515000, 'schedule_id': 'usd-v2',
         'rounding': 'half_up', 'policy': current.POLICY, 'expires_at': (NOW-timedelta(days=7)).isoformat()}
    offer = {'id': SOURCE, 'buyer_id': BUYER, 'listing_id': LINE, 'listing_revision': 1, 'state': 'accepted',
             'revision': 3, 'accepted_revision': 2, 'accepted_at': NOW, 'snapshot': q, 'expires_at': NOW}
    request = request_for({'l14_offers': offer})
    monkeypatch.setattr(routes.peers, 'service', lambda *a: 'orders')
    async def listing(*args):
        return {}
    monkeypatch.setattr(routes.peers, 'listing', listing)
    result = asyncio.run(routes.validation(QUOTE, BUYER, request))
    assert result['source_revision'] == 2 and result['expires_at'] is None


@pytest.mark.parametrize('change', ['revoked', 'withdrawn', 'changed', 'nonusd'])
def test_current_assessment_and_identity_providers_fail_closed(monkeypatch, change):
    q = snapshot()
    async def call(request, service, method, path, **kwargs):
        if service == 'identity':
            return {'id': str(ORG), 'state': 'revoked' if change == 'revoked' else 'active',
                    'authenticated_business': True, 'platform_onboarded': True, 'kind': 'brand',
                    'capabilities': ['customization']}
        if service == 'catalog':
            return {'id': str(SOURCE), 'revision': 2 if change == 'changed' else 1,
                    'buyer_id': str(BUYER), 'brand_id': str(ORG), 'consent_effective': change != 'withdrawn'}
        return {'id': str(ASSESSMENT), 'revision': 1, 'request_id': str(SOURCE), 'request_revision': 1,
                'organization_id': str(ORG), 'buyer_id': str(BUYER), 'status': 'feasible', 'current': True,
                'line_ids': [str(LINE)], 'lines': [{k: v for k,v in q['lines'][0].items() if k != 'amount_minor'}],
                'currency': 'LBP' if change == 'nonusd' else 'USD', 'technical_summary': 'Current technical assessment'}
    monkeypatch.setattr(assessed.peers, 'call', call)
    with pytest.raises(PublicError):
        asyncio.run(assessed.current_source(None, 'brand', q))
