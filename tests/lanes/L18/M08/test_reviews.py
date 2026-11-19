import importlib.util
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pytest

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('reviews', ROOT / 'services/trust/modules/transaction-reviews/model.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def setup(tmp_path):
    source = json.loads((ROOT / 'packages/contracts-trust/transaction-reviews/fixtures.json').read_text())['released']
    access = {'active': True, 'organization_id': 'business-1', 'subject_id': 'purchase-1'}
    store = module.Reviews(tmp_path / 'reviews.db', lambda actor, organization, subject: {**access, 'actor_id': actor}, lambda subject: source,
                           lambda: datetime(2026, 11, 17, 10, tzinfo=timezone.utc))
    command = dict(operation_id='operation-1', subject_id='purchase-1', watch_id='watch-1', actor_id='buyer-1',
                   organization_id='business-1', expected_revision=0, source_revision=3, quote_revision=2,
                   policy_revision=1, kind='create', rating=1, text='نقد mixed 🕰️')
    return store, source, access, command


def test_restart_replay_and_public_privacy(setup):
    store, source, access, c = setup
    result = store.command(c)
    public_reference = store.public('seller-1')['items'][0]['review_ref']
    path = store.db.execute('PRAGMA database_list').fetchone()[2]
    store.db.close()
    store = module.Reviews(path, lambda actor, organization, subject: {**access, 'actor_id': actor}, lambda subject: source)
    assert store.command(c) == result
    assert store.lookup(c['operation_id'], c['actor_id'], c['organization_id'], c['subject_id']) == result
    public = store.public('seller-1')
    assert public['items'][0]['review_ref'] == public_reference
    assert public['distribution'] == [1, 0, 0, 0, 0]
    assert public['average'] == 1
    assert set(public['items'][0]) == {'review_ref', 'rating', 'text', 'reply'}
    access['active'] = False
    with pytest.raises(module.Refused, match='scope_denied'):
        store.command(c)


@pytest.mark.parametrize('field,value', [('rating', 0), ('rating', 6), ('rating', True), ('actor_id', 'seller-1'), ('organization_id', 'other'), ('source_revision', 2), ('expected_revision', 1)])
def test_negative(setup, field, value):
    store, _, _, c = setup
    c[field] = value
    with pytest.raises(module.Refused): store.command(c)
    assert store.public('seller-1')['total'] == 0


@pytest.mark.parametrize('seconds,allowed', [(-1, True), (0, True), (1, False)])
def test_release_boundary(setup, seconds, allowed):
    store, source, _, c = setup
    source['released_at'] = (datetime(2026, 11, 17, 10, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()
    if allowed: assert store.command(c)['state'] == 'confirmed'
    else:
        with pytest.raises(module.Refused): store.command(c)


def test_reply_report_independent_decision(setup):
    store, _, access, c = setup
    store.command(c)
    c.update(operation_id='reply-1', actor_id='colleague-1', expected_revision=1, kind='reply', text='شكراً')
    with pytest.raises(module.Refused): store.command(c)
    access.update(seller_reply=True, seller_id='seller-1')
    store.command(c)
    c.update(operation_id='reply-2', expected_revision=2)
    with pytest.raises(module.Refused): store.command(c)
    c.update(operation_id='report-1', actor_id='reader-1', kind='report', reason='Reason')
    store.command(c)
    assert store.public('seller-1')['total'] == 1
    c.update(operation_id='decision-1', expected_revision=3, kind='decide', visible=False)
    access.update(moderate=True, assigned_review='purchase-1')
    with pytest.raises(module.Refused): store.command(c)
    access.pop('seller_id')
    with pytest.raises(module.Refused): store.command(c)
    c['actor_id'] = 'moderator-1'
    store.command(c)
    assert store.public('seller-1')['total'] == 0
    assert store.db.execute('SELECT reason FROM l18_decisions').fetchone()[0] == 'Reason'


def test_duplicate_conflict_and_timeout(setup):
    store, _, _, c = setup
    store.command(c)
    c['text'] = 'changed'
    with pytest.raises(module.Refused, match='operation_conflict'): store.command(c)
    c.update(operation_id='new-operation', expected_revision=0)
    with pytest.raises(module.Refused, match='stale_revision'): store.command(c)
    store.purchase = lambda subject: None
    with pytest.raises(module.Refused, match='unavailable'): store.command(c)
    assert store.db.execute('SELECT count(*) FROM l18_receipts').fetchone()[0] == 1


@pytest.mark.parametrize('source', [None, {}, {'state': 'pending'}])
def test_missing_source_fails_closed(setup, source):
    store, _, _, c = setup
    store.purchase = lambda subject: source
    with pytest.raises(module.Refused, match='unavailable'): store.command(c)


def test_unreleased_and_malformed_time(setup):
    store, source, _, c = setup
    source['state'] = 'pending'
    source['released_at'] = None
    with pytest.raises(module.Refused, match='purchase_not_released'): store.command(c)
    source['state'] = 'released'
    with pytest.raises(module.Refused, match='unavailable'): store.command(c)


def test_provider_failure(setup):
    store, _, _, c = setup
    def unavailable(subject): raise TimeoutError()
    store.purchase = unavailable
    with pytest.raises(module.Refused, match='unavailable'): store.command(c)


def test_pagination_all_rows(setup):
    store, source, _, c = setup
    for index in range(1000):
        reference = f'purchase-{index}'
        source['purchase_id'] = reference
        c.update(subject_id=reference, operation_id=f'operation-{index}')
        # This fixture grants only this exact current record.
        store.authority = lambda actor, organization, subject: dict(active=True, organization_id=organization, actor_id=actor, subject_id=subject)
        store.command(c)
    assert store.public('seller-1')['total'] == 1000
    assert sum(len(store.public('seller-1', page)['items']) for page in range(1, 51)) == 1000
    assert store.public('seller-1', 50)['next_page'] is None


def test_current_authority_timeout_and_malformed(setup):
    store, _, _, c = setup
    def unavailable(*args): raise TimeoutError()
    store.authority = unavailable
    with pytest.raises(module.Refused, match='unavailable'): store.command(c)
    store.authority = lambda *args: []
    with pytest.raises(module.Refused, match='unavailable'): store.command(c)


def test_boundary_capacity_and_timeout(tmp_path):
    import asyncio
    import sys
    import time
    import types
    package = types.ModuleType('l18_reviews')
    package.__path__ = [str(ROOT / 'services/trust/modules/transaction-reviews')]
    sys.modules['l18_reviews'] = package
    from l18_reviews.adapter import Boundary
    class Store:
        db = types.SimpleNamespace(close=lambda: None)
        def command(self, command):
            time.sleep(2.1)
            return {'state': 'confirmed'}
    async def exercise():
        boundary = Boundary(Store)
        c = {'actor_id': 'buyer', 'organization_id': 'business', 'operation_id': 'same-operation'}
        first = asyncio.create_task(boundary.execute(c, 'buyer', 'business'))
        await asyncio.sleep(0)
        refused = await boundary.execute(c, 'buyer', 'business')
        assert refused['state'] == 'unavailable'
        assert refused['code'] == 'capacity_unavailable'
        pending = await first
        assert pending['state'] == 'pending'
        assert pending['operation_id'] == c['operation_id']
        assert boundary.busy
        await asyncio.sleep(.2)
        assert not boundary.busy
        boundary.executor.shutdown()
    asyncio.run(exercise())


def test_seller_colleague_cannot_review_own_business(setup):
    store, _, access, c = setup
    access['seller_id'] = 'seller-1'
    with pytest.raises(module.Refused, match='review_denied'): store.command(c)


def test_reply_author_cannot_moderate_after_restart(setup):
    store, source, access, c = setup
    store.command(c)
    access.update(seller_reply=True, seller_id='seller-1')
    c.update(operation_id='reply', kind='reply', actor_id='colleague-1', expected_revision=1)
    store.command(c)
    path = store.db.execute('PRAGMA database_list').fetchone()[2]
    store.db.close()
    store = module.Reviews(path, lambda actor, organization, subject: {**access, 'actor_id': actor}, lambda subject: source)
    access.clear()
    access.update(active=True, organization_id='business-1', subject_id='purchase-1')
    c.update(operation_id='report', kind='report', actor_id='reader-1', expected_revision=2, reason='Reason')
    store.command(c)
    access.update(moderate=True, assigned_review='purchase-1')
    c.update(operation_id='decision', kind='decide', actor_id='colleague-1', expected_revision=3, visible=False)
    with pytest.raises(module.Refused, match='independent_assignment_required'):
        store.command(c)
    assert store.public('seller-1')['total'] == 1
    assert store.db.execute('SELECT count(*) FROM l18_decisions').fetchone()[0] == 0
    c.update(actor_id='moderator-1')
    assert store.command(c)['state'] == 'confirmed'


def test_older_reply_without_authorship_denies_moderation(setup):
    store, _, access, c = setup
    store.command(c)
    store.db.execute("UPDATE l18_reviews SET reply='Retained reply'")
    c.update(operation_id='report', kind='report', actor_id='reader-1', expected_revision=1, reason='Reason')
    store.command(c)
    access.update(moderate=True, assigned_review='purchase-1')
    c.update(operation_id='decision', kind='decide', actor_id='moderator-1', expected_revision=2, visible=False)
    with pytest.raises(module.Refused, match='independent_assignment_required'):
        store.command(c)
    assert store.public('seller-1')['total'] == 1


@pytest.mark.parametrize('text', ['a' * 2000, 'ع' * 2000, '🕰' * 2000])
def test_full_length_review(setup, text):
    store, _, _, c = setup
    c['text'] = text
    assert store.command(c)['state'] == 'confirmed'
    assert store.public('seller-1')['items'][0]['text'] == text


def test_public_reference_report_replay_and_scope(setup):
    store, _, access, c = setup
    store.command(c)
    reference = store.public('seller-1')['items'][0]['review_ref']
    assert reference != c['subject_id']
    c.update(subject_id=reference, operation_id='public-report', actor_id='reader-1',
             kind='report', expected_revision=1, reason='Reason')
    result = store.command(c)
    assert result['subject_id'] == reference
    assert store.command(c) == result
    assert store.lookup('public-report', 'reader-1', 'business-1', reference) == result
    assert store.public('seller-1')['items'][0]['review_ref'] == reference
    assert store.db.execute('SELECT review FROM l18_reports').fetchone()[0] == 'purchase-1'
    access['active'] = False
    with pytest.raises(module.Refused, match='scope_denied'):
        store.command(c)


def test_pagination_beyond_ten_thousand_rows(setup):
    store, _, _, c = setup
    store.command(c)
    store.db.execute('BEGIN')
    store.db.executemany(
        'INSERT INTO l18_reviews (id,seller,buyer,organization,watch,rating,text,revision,review_ref) VALUES(?,?,?,?,?,?,?,?,?)',
        ((f'purchase-extra-{index}', 'seller-1', 'buyer-1', 'business-1',
          f'watch-extra-{index}', 1, 'Synthetic review', 1, f'review-extra-{index}')
         for index in range(10000)))
    store.db.execute('COMMIT')
    page = store.public('seller-1', 500)
    assert page['total'] == 10001
    assert len(page['items']) == 20
    assert page['next_page'] == 501
    last = store.public('seller-1', page['next_page'])
    assert last['total'] == 10001
    assert len(last['items']) == 1
    assert last['next_page'] is None
    assert not {item['review_ref'] for item in page['items']} & {item['review_ref'] for item in last['items']}


@pytest.mark.parametrize('page', [0, -1, True, 1.5])
def test_invalid_page(setup, page):
    store, _, _, _ = setup
    with pytest.raises(module.Refused, match='invalid_page'):
        store.public('seller-1', page)


def test_public_route_accepts_page_501(setup):
    import sys
    import types
    from fastapi import FastAPI
    package = types.ModuleType('l18_review_routes')
    package.__path__ = [str(ROOT / 'services/trust/modules/transaction-reviews')]
    sys.modules['l18_review_routes'] = package
    from l18_review_routes.routes import router_for

    class Store:
        db = types.SimpleNamespace(close=lambda: None)

        def public(self, seller, page):
            assert seller == 'seller-1'
            return {'page': page}

    app = FastAPI()
    app.include_router(router_for(None, Store, lambda: {}))
    parameter = next(parameter for parameter in
                     app.openapi()['paths']['/v1/transaction-reviews/sellers/{seller_id}']['get']['parameters']
                     if parameter['name'] == 'page')
    assert parameter['schema']['minimum'] == 1
    assert 'maximum' not in parameter['schema']
    endpoint = next(route.endpoint for route in app.routes
                    if getattr(route, 'path', None) == '/v1/transaction-reviews/sellers/{seller_id}')
    assert endpoint('seller-1', 501) == {'page': 501}
