import httpx
import pytest
from fastapi import FastAPI
from l20_private_review.routes import router
from test_review import CASE, DATA, OPERATOR, REVIEWER, Authority, Store, command
from bt_contracts.eligibility.private_review.models import Source
import l20_private_review.routes as routes


def client(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    store = Store()
    monkeypatch.setattr(routes, 'Repository', lambda *_: store)
    app.state.pool = object()
    @app.middleware('http')
    async def request_id(request, call_next):
        request.state.request_id = 'synthetic-request'
        return await call_next(request)
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test'), store


@pytest.mark.asyncio
async def test_adapter_validation_missing_authority_and_no_store(monkeypatch):
    app, http, _ = client(monkeypatch)
    root = f'/v1/private-reviews/{CASE}'
    async with http:
        for path, status in [(root, 403), ('/v1/private-reviews/invalid', 422), (root+'/history?page=bad', 422)]:
            result = await http.get(path)
            assert result.status_code == status
            assert result.headers['cache-control'] == 'private, no-store'
            assert set(result.json()['error']['details']['messages']) == {'en', 'ar'}
        assert (await http.get(root, headers={'Authorization': f'Bearer {REVIEWER}'})).status_code == 503
        result = await http.post(root+'/commands', json={'reason': 'invalid'})
        assert result.status_code == 422 and result.json()['error']['code'] == 'invalid_fields'
        app.state.private_review_authority = Authority()
        action = command(Source.model_validate(DATA['source']), 'reassign', 0, reviewer_id=REVIEWER)
        result = await http.post('/v1/private-reviews/00000000-0000-0000-0000-000000000099/commands', json=action.model_dump(mode='json'), headers={'Authorization': f'Bearer {OPERATOR}'})
        assert result.status_code == 403


@pytest.mark.asyncio
async def test_operator_recovers_only_own_assignment_receipt(monkeypatch):
    app, http, _ = client(monkeypatch)
    authority = app.state.private_review_authority = Authority()
    action = command(authority.source, 'reassign', 0, reviewer_id=REVIEWER)
    root = f'/v1/private-reviews/{CASE}'
    headers = {'Authorization': f'Bearer {OPERATOR}'}
    async with http:
        first = await http.post(root+'/commands', json=action.model_dump(mode='json'), headers=headers)
        assert first.status_code == 200
        assert (await http.get(root+f'/operations/{action.operation_id}', headers=headers)).json() == first.json()
        assert (await http.get(root+'/evidence', headers=headers)).status_code == 403
        assert (await http.get(root+'/history', headers=headers)).status_code == 403
