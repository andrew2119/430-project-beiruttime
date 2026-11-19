import importlib.util
import sys
import types
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from test_questions import store, run, body

root = Path(__file__).resolve().parents[4] / 'services/communications/modules/listing-questions'
package = types.ModuleType('listing_questions_test')
package.__path__ = [str(root)]
sys.modules[package.__name__] = package
for name in ('model', 'adapter', 'routes'):
    spec = importlib.util.spec_from_file_location(f'{package.__name__}.{name}', root / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
routes = sys.modules['listing_questions_test.routes']
# Keep the adapter's rejection type identical to the shared fixture's module.
routes.Rejected = sys.modules['listing_questions_test.adapter'].Rejected = __import__('test_questions').m.Rejected


def request(store, method, path, **kwargs):
    app = FastAPI()
    async def principal(request):
        if request.headers.get('x-test-actor') == 'visitor':
            return None
        return {'actor_id': request.headers.get('x-test-actor', 'buyer'), 'organization_id': None}
    app.include_router(routes.build_router(store, principal))
    async def send():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            return await client.request(method, '/v1/listing-questions/listing' + path, **kwargs)
    return run(send())


def test_routes_and_stable_errors(store):
    response = request(store, 'POST', '/commands', json=body())
    assert response.status_code == 200
    assert request(store, 'GET', '/operations/op').json() == response.json()
    assert request(store, 'GET', '').json()['total'] == 1
    denied = request(store, 'GET', '', headers={'x-test-actor': 'revoked'})
    assert denied.status_code == 403
    assert denied.json()['error']['code'] == 'denied'
    assert set(denied.json()['error']['message']) == {'en', 'ar'}


@pytest.mark.parametrize('path,payload', [('/suggest', {}), ('/commands', {}), ('/commands', []), ('/suggest', {'text': 5}), ('/suggest', None)])
def test_malformed_payloads_never_become_server_errors(store, path, payload):
    assert request(store, 'POST', path, json=payload).status_code == 422


def test_request_and_page_bounds(store):
    assert request(store, 'POST', '/commands', content='x'*16385).status_code == 422
    assert request(store, 'GET', '?page=50001').status_code == 422
    assert request(store, 'GET', '?page=-1').status_code == 422


def test_public_reads_still_check_listing_scope(store):
    assert request(store, 'POST', '/commands', json=body()).status_code == 200
    original = store.authority
    calls = []
    async def authority(actor, organization, listing):
        calls.append((actor, organization, listing))
        scope = await original(actor, organization, listing)
        return scope | {'can_ask': actor is not None, 'can_answer': False, 'can_report': actor is not None}
    store.authority = authority
    headers = {'x-test-actor': 'visitor'}
    public = request(store, 'GET', '', headers=headers)
    assert public.status_code == 200
    assert public.json()['items'][0]['question'] == 'Is it original?'
    assert calls[-1] == (None, None, 'listing')
    assert request(store, 'POST', '/suggest', json={'text': 'Original?', 'page': 0}, headers=headers).status_code == 200
    assert request(store, 'POST', '/commands', json=body(), headers=headers).status_code == 403
    assert request(store, 'GET', '/review/q', headers=headers).status_code == 403
    assert request(store, 'GET', '/operations/op', headers=headers).status_code == 403
    async def denied(*args):
        return {'allowed': False}
    store.authority = denied
    assert request(store, 'GET', '', headers=headers).status_code == 403


@pytest.mark.parametrize('page', ['-1', '50001', 'text', '1.5', '١', ''])
def test_invalid_pages_use_bilingual_envelope(store, page):
    response = request(store, 'GET', '?page=' + page)
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'invalid'
    assert set(response.json()['error']['message']) == {'en', 'ar'}


def test_suggestion_pages_are_reachable_and_bounded(store):
    for i in range(21):
        question = f'q{i}'
        run(store.command('buyer', None, 'listing', body(operation_id=f'ask{i}', question_id=question)))
        run(store.command('seller', None, 'listing', body(kind='answer', operation_id=f'answer{i}', question_id=question, expected_revision=1, text='Yes')))
    first = request(store, 'POST', '/suggest', json={'text': 'Is it original?', 'page': 0}).json()
    last = request(store, 'POST', '/suggest', json={'text': 'Is it original?', 'page': 1}).json()
    assert first['total'] == last['total'] == 21
    assert len(first['items']) == 20 and len(last['items']) == 1
    assert last['page'] == 1
    assert len({row['id'] for row in first['items'] + last['items']}) == 21
    for page in (-1, 50001, True, '1', None):
        assert request(store, 'POST', '/suggest', json={'text': 'Is it original?', 'page': page}).status_code == 422


def test_private_review_pages_keep_every_reason_reachable(store):
    run(store.command('buyer', None, 'listing', body()))
    for i in range(21):
        run(store.command('buyer', None, 'listing', body(kind='report', operation_id=f'report{i:02}', expected_revision=1+i*2, text=f'Report {i}')))
        run(store.command('buyer', None, 'listing', body(kind='appeal', operation_id=f'appeal{i:02}', expected_revision=2+i*2, text=f'Appeal {i}')))
    headers = {'x-test-actor': 'moderator'}
    first = request(store, 'GET', '/review/q', headers=headers).json()
    last = request(store, 'GET', '/review/q?reports_page=1&appeals_page=1', headers=headers).json()
    assert first['reports_total'] == last['reports_total'] == 21
    assert first['appeals_total'] == last['appeals_total'] == 21
    for kind in ('reports', 'appeals'):
        assert len(first[kind]) == 20 and len(last[kind]) == 1
        assert len({row['reason'] for row in first[kind] + last[kind]}) == 21
        assert last[f'{kind}_page'] == 1
    mixed = request(store, 'GET', '/review/q?reports_page=1', headers=headers).json()
    assert mixed['reports'] == last['reports'] and mixed['appeals'] == first['appeals']
    empty = request(store, 'GET', '/review/q?reports_page=50000', headers=headers).json()
    assert empty['reports'] == [] and empty['reports_total'] == 21
    for key in ('reports_page', 'appeals_page'):
        for value in ('-1', '50001', '1.5', 'true'):
            response = request(store, 'GET', f'/review/q?{key}={value}', headers=headers)
            assert response.status_code == 422
            assert set(response.json()['error']['message']) == {'en', 'ar'}
    assert request(store, 'GET', '/review/q?reports_page=1', headers={'x-test-actor': 'revoked'}).status_code == 403
    assert store.db.execute('SELECT count(*) FROM l18_receipts').fetchone()[0] == 43
