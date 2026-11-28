"""Pure public response validation with deterministic, isolated reads."""
import asyncio
import copy
import importlib
import json
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[4]
NAME = 'catalog_discovery_checks'
package = types.ModuleType(NAME)
package.__path__ = [str(ROOT / 'services/catalog/modules/discovery')]
sys.modules[NAME] = package
reads = importlib.import_module(NAME + '.dependencies')
search = importlib.import_module(NAME + '.search')
models = importlib.import_module(NAME + '.models')
source = importlib.import_module(NAME + '.source_contract')
FACTS = json.loads((ROOT / 'packages/contracts-catalog/discovery/fixtures/public-facts.v1.json').read_text())
SUBJECT = SimpleNamespace(seller_id=UUID(FACTS['seller_id']), physical_watch_id=UUID(FACTS['watch_id']), revision=3, organization_id=None)


class Client:
    def __init__(self, body=None, status=200, delay=0):
        self.body, self.status, self.delay = body, status, delay
        self.calls = []

    async def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        await asyncio.sleep(self.delay)
        return httpx.Response(self.status, json=self.body)


def run(body=FACTS, status=200):
    return asyncio.run(reads.Reads(identity=Client(body, status)).public_facts(SUBJECT))


def test_empty_is_actual_zero_and_repeat_is_stable():
    assert run().released_sales == 0
    assert run() == run()
    assert run().inspection is None


@pytest.mark.parametrize('status', [401, 403, 404, 409, 503])
def test_denied_and_unavailable_are_not_facts(status):
    assert run(status=status) is None


@pytest.mark.parametrize('field,value', [
    ('seller_id', '00000000-0000-0000-0000-000000000009'),
    ('organization_id', '00000000-0000-0000-0000-000000000009'),
    ('watch_id', '00000000-0000-0000-0000-000000000009'),
    ('listing_revision', 2), ('listing_revision', 4),
    ('review_distribution', [1, 0, 0, 0, 0]),
    ('private_evidence', 'restricted'), ('released_sales', True),
])
def test_wrong_scope_stale_future_and_private_fields_fail_closed(field, value):
    body = copy.deepcopy(FACTS)
    body[field] = value
    assert run(body) is None


def test_lost_response_then_same_read_recovers():
    async def scenario():
        client = Client(FACTS, delay=.05)
        reader = reads.Reads(identity=client)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(.001):
                await reader.public_facts(SUBJECT)
        client.delay = 0
        assert await reader.public_facts(SUBJECT) is not None
        assert client.calls[0] == client.calls[1]
    asyncio.run(scenario())


@pytest.mark.parametrize('count', [0, 1, 1000, 1000000])
def test_totals_are_server_counts_not_page_lengths(count):
    now = datetime.now(timezone.utc)
    filters = search.Filters()
    body = dict(schema_version='catalog-public-total.v1', criteria=filters.fingerprint(), total=count, revision=1, as_of=now.isoformat())
    assert asyncio.run(reads.Reads(orders=Client(body)).search_total(filters, now)) == count
    body['as_of'] = (now-timedelta(seconds=16)).isoformat()
    assert asyncio.run(reads.Reads(orders=Client(body)).search_total(filters, now)) is None
    body['criteria'] = '0'*32
    assert asyncio.run(reads.Reads(orders=Client(body)).search_total(filters, now)) is None


def test_only_active_dollars_and_exact_minor_values():
    with pytest.raises(Exception):
        search.Filters(currency='LBP')
    with pytest.raises(ValidationError):
        models.PublicMoney(amount='1.001', currency='USD')
    assert str(models.PublicMoney(amount='5000.01', currency='USD').amount) == '5000.01'


def test_shareable_pagination_over_thousand_rows_and_filter_binding(monkeypatch):
    service = importlib.import_module(NAME + '.service')
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [SimpleNamespace(
        id=UUID(int=index+1), revision=1, organization_id=None, seller_type='private',
        facts=SimpleNamespace(brand='Sample', model=f'Model {index}', location='Beirut',
            price_minor=500001, currency='USD', sale_mode='fixed_price'),
        cover_id=UUID(int=2001+index), published_at=now, is_demo=True,
    ) for index in range(1000)]

    async def candidates(pool, filters, cursor):
        start = int(search.decode_cursor(cursor, filters, now)[0])+1 if cursor else 0
        return [(row, str(index)) for index, row in enumerate(rows[start:start+49], start)], start+49 < len(rows), now, now

    class PublicReads:
        async def timing_batch(self, ids): return {}, set()
        async def availability(self, row): return SimpleNamespace(status='available')
        async def search_total(self, filters, timestamp): return 1000

    monkeypatch.setattr(service, '_read_candidates', candidates)

    async def scenario():
        cursor, ids = '', []
        while True:
            page = await service.find(None, PublicReads(), search.Filters(), cursor)
            assert page.total == 1000
            assert len(page.items) <= 12
            ids.extend(item.id for item in page.items)
            cursor = page.next_cursor
            if not cursor: break
        assert ids == [str(row.id) for row in rows]
        stale = search.encode_cursor(search.Filters(), '0', rows[0].id, now)
        with pytest.raises(Exception):
            search.decode_cursor(stale, search.Filters(brand='Different'), now)
        with pytest.raises(Exception):
            search.decode_cursor(stale, search.Filters(), now+timedelta(days=2))
    asyncio.run(scenario())


def test_private_inspection_and_business_membership_are_distinct():
    service = importlib.import_module(NAME + '.service')
    private = SimpleNamespace(seller_type='private', facts=SimpleNamespace(sale_mode='fixed_price'))
    assert service.Resolved(private, None, None, None, True).state == 'unavailable'
    business = SimpleNamespace(seller_type='dealer', facts=SimpleNamespace(sale_mode='fixed_price'))
    membership = SimpleNamespace(state='revoked', platform_onboarded=True, authenticated_business=True, capabilities=['sales'])
    assert service.Resolved(business, SimpleNamespace(status='available'), membership, None, True).state == 'unavailable'


def test_document_and_gallery_source_bindings():
    row = dict(
        id=str(UUID(int=1)), seller_id=str(UUID(int=2)), organization_id=None, seller_type='private', seller_label='Sample seller',
        physical_watch_id=str(UUID(int=3)), revision=1, status='published',
        facts=dict(brand='Sample', model='Sample watch', reference='', year=None, condition='Declared condition', component_wear={},
            location='Beirut', included=[], no_documents=True, modified=False, modifications=[], ownership_confirmed=True,
            sale_mode='fixed_price', currency='USD', price_minor=500000),
        photo_ids=[str(UUID(int=4))], cover_id=str(UUID(int=4)), is_demo=True,
        registration=dict(watch_id=str(UUID(int=3)), listing_id=str(UUID(int=1)), sale_mode='fixed', revision=1),
        rules_version='sample.v1', published_at='2026-01-01T00:00:00Z',
    )
    assert source.PublicListing.model_validate(row).facts.no_documents is True
    row['facts']['included'] = ['papers']
    with pytest.raises(ValidationError): source.PublicListing.model_validate(row)
    row['facts']['no_documents'] = False
    assert source.PublicListing.model_validate(row).facts.no_documents is False
    row['photo_ids'] *= 2
    with pytest.raises(ValidationError): source.PublicListing.model_validate(row)


def test_new_total_timestamp_is_checked_after_receipt():
    filters = search.Filters()
    before = datetime.now(timezone.utc)

    class FreshClient:
        async def request(self, *args, **kwargs):
            await asyncio.sleep(.001)
            return httpx.Response(200, json=dict(schema_version='catalog-public-total.v1', criteria=filters.fingerprint(), total=1, revision=1, as_of=datetime.now(timezone.utc).isoformat()))
    assert asyncio.run(reads.Reads(orders=FreshClient()).search_total(filters, before)) == 1


def test_contract_cases_are_closed_and_recoverable():
    cases = json.loads((ROOT / 'packages/contracts-catalog/discovery/fixtures/public-read-cases.v1.json').read_text())['cases']
    indexed = {case['name']: case for case in cases}
    assert run(indexed['success']['body']) is not None
    assert run(indexed['denied']['body'], indexed['denied']['status']) is None
    assert run(indexed['stale']['body']) is None
    assert run(indexed['wrong_business']['body']) is None
    assert indexed['lost_response']['status'] is None
    assert run(indexed['success']['body']) is not None


def test_history_paginates_thousand_entries_with_stable_snapshot():
    entries = [dict(occurred_at='2026-01-01T00:00:00Z', summary_en=f'Released record {index} ⌚', summary_ar=f'سجل مكتمل {index} ⌚') for index in range(1000)]

    class HistoryClient:
        async def request(self, method, path, **kwargs):
            params = kwargs['params']
            start = int(params.get('cursor', '0'))
            body = copy.deepcopy(FACTS)
            body['history'] = entries[start:start+100]
            body['history_next_cursor'] = str(start+100) if start+100 < len(entries) else None
            return httpx.Response(200, json=body)

    async def scenario():
        reader = reads.Reads(identity=HistoryClient())
        cursor, collected = '', []
        while True:
            page = await reader.public_facts(SUBJECT, cursor, 1)
            assert page is not None
            assert page == await reader.public_facts(SUBJECT, cursor, 1)
            assert len(page.history) <= 100
            collected.extend(item.model_dump(mode='json') for item in page.history)
            if page.history_next_cursor is None:break
            cursor = page.history_next_cursor
        assert [entry['summary_en'] for entry in collected] == [entry['summary_en'] for entry in entries]
    asyncio.run(scenario())


@pytest.mark.parametrize('field,value', [
    ('revision', 2), ('listing_revision', 2),
    ('organization_id', '00000000-0000-0000-0000-000000000009'),
    ('history_next_cursor', 'position'), ('history_next_cursor', ''),
])
def test_history_continuation_rejects_changed_scope_revision_and_nonadvancing_cursor(field, value):
    body = copy.deepcopy(FACTS)
    body[field] = value
    assert asyncio.run(reads.Reads(identity=Client(body)).public_facts(SUBJECT, 'position', 1)) is None


def test_history_service_checks_current_visibility_and_recovers(monkeypatch):
    service = importlib.import_module(NAME + '.service')
    calls = []

    async def current(pool, reader, identifier):
        calls.append(identifier)
        return SUBJECT

    monkeypatch.setattr(service, 'canonical', current)

    async def scenario():
        client = Client(FACTS, status=403)
        reader = reads.Reads(identity=client)
        with pytest.raises(Exception):await service.history(None, reader, 'watch', 'position', 3, 1)
        client.status = 200
        page = await service.history(None, reader, 'watch', 'position', 3, 1)
        assert page.next_cursor is None and page.listing_revision == 3
        assert client.calls[0] == client.calls[1]
        count = len(client.calls)
        with pytest.raises(Exception):await service.history(None, reader, 'watch', 'position', 2, 1)
        assert len(client.calls) == count
        client.delay = 1
        with pytest.raises(Exception):await service.history(None, reader, 'watch', 'position', 3, 1)
        client.delay = 0
        assert await service.history(None, reader, 'watch', 'position', 3, 1) == page
    asyncio.run(scenario())
    assert len(calls) == 5


def test_history_schema_matches_runtime_and_exposes_continuation():
    schema = json.loads((ROOT / 'packages/contracts-catalog/discovery/public-facts.v1.schema.json').read_text())
    assert schema['properties'] == reads.PublicFacts.model_json_schema()['properties']
    assert 'history_next_cursor' in schema['required']
    assert schema['properties']['history']['maxItems'] == 100


def test_published_history_continuation_fixtures():
    cases = json.loads((ROOT / 'packages/contracts-catalog/discovery/fixtures/public-read-cases.v1.json').read_text())['cases']
    indexed = {case['name']: case for case in cases}
    first = run(indexed['history_first']['body'])
    assert first.history_next_cursor == 'history-page-2'
    reader = reads.Reads(identity=Client(indexed['history_last']['body']))
    last = asyncio.run(reader.public_facts(SUBJECT, first.history_next_cursor, first.revision))
    assert last.history_next_cursor is None
    assert first.history[0].summary_en != last.history[0].summary_en


@pytest.mark.parametrize('restriction', ['revoked', 'missing', 'onboarding', 'authentication', 'sales'])
def test_initial_history_requires_current_business_eligibility_and_recovers(monkeypatch, restriction):
    service = importlib.import_module(NAME + '.service')
    listing = SimpleNamespace(
        id=UUID(int=11), revision=3, organization_id=UUID(int=12), seller_type='dealer',
        seller_id=SUBJECT.seller_id, seller_label='Sample seller', physical_watch_id=SUBJECT.physical_watch_id,
        facts=SimpleNamespace(brand='Sample', model='Watch', location='Beirut', price_minor=500000,
            currency='USD', sale_mode='fixed_price', modifications=[], no_documents=True,
            reference='', year=None, component_wear={}, condition='Declared', included=[], modified=False),
        cover_id=UUID(int=13), photo_ids=[UUID(int=13)], published_at=datetime.now(timezone.utc), is_demo=True,
    )
    membership = SimpleNamespace(state='active', platform_onboarded=True, authenticated_business=True,
        capabilities=['sales'], public_name='Sample business')
    body = copy.deepcopy(FACTS)
    body.update(organization_id=str(listing.organization_id), released_sales=7,
        history=[dict(occurred_at='2026-01-01T00:00:00Z', summary_en='Released record', summary_ar='سجل مكتمل')],
        history_next_cursor='next-page')

    class PublicReads:
        def __init__(self):
            self.current = membership
            self.facts_calls = 0

        async def business(self, source):return self.current
        async def availability(self, source):return SimpleNamespace(status='available')
        async def credits(self, source):return None
        async def public_facts(self, source, cursor='', revision=None):
            self.facts_calls += 1
            return reads.PublicFacts.model_validate(body)

    async def current(pool, identifier):return listing
    monkeypatch.setattr(service, 'raw_detail', current)

    async def scenario():
        reader = PublicReads()
        if restriction == 'missing':reader.current = None
        elif restriction == 'revoked':membership.state = 'revoked'
        elif restriction == 'onboarding':membership.platform_onboarded = False
        elif restriction == 'authentication':membership.authenticated_business = False
        else:membership.capabilities = []
        for _ in range(2):
            detail = await service.view(None, reader, str(listing.id))
            assert detail.sale_state == 'unavailable'
            assert detail.history is None and detail.history_revision is None and detail.history_next_cursor is None
            assert detail.seller.completed_sales is None and detail.seller.joined_at is None
            assert detail.seller.city is None and detail.seller.review_distribution is None
            with pytest.raises(Exception):await service.history(None, reader, str(listing.id), '', 3, 1)
        assert reader.facts_calls == 0
        membership.state = 'active'
        membership.platform_onboarded = membership.authenticated_business = True
        membership.capabilities = ['sales']
        reader.current = membership
        detail = await service.view(None, reader, str(listing.id))
        assert detail.sale_state == 'available' and detail.seller.completed_sales == 7
        assert detail.history[0].summary_en == 'Released record'
        assert detail.history_revision == 1 and detail.history_next_cursor == 'next-page'
        page = await service.history(None, reader, str(listing.id), '', 3, 1)
        assert page.history == detail.history
        assert reader.facts_calls == 2
    asyncio.run(scenario())


@pytest.mark.parametrize('missing', ['summary_en', 'summary_ar'])
def test_history_requires_both_system_languages(missing):
    entry = dict(occurred_at='2026-01-01T00:00:00Z', summary_en='Released record', summary_ar='سجل مكتمل')
    del entry[missing]
    with pytest.raises(ValidationError):models.HistoryEntry.model_validate(entry)


def test_history_preserves_user_note_verbatim():
    note = 'ملاحظة Watch ⌚'
    entry = models.HistoryEntry(occurred_at='2026-01-01T00:00:00Z', summary_en='Released record', summary_ar='سجل مكتمل', user_note=note)
    assert entry.user_note == note
