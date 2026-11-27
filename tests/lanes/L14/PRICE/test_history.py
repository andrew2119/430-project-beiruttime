import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

from conftest import load

routes = load('price_quotes.routes', 'services/pricing/modules/quotes/routes.py')


def test_history_uses_owner_filtered_server_total_and_real_page():
    owner = UUID(int=1)
    class Connection:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def fetchrow(self, sql, *args):
            assert "owner_id=$1 AND snapshot->>'currency'='USD'" in sql
            assert 'WITH visible AS MATERIALIZED' in sql
            assert 'count(*) FROM visible' in sql
            assert 'ORDER BY created_at DESC,id DESC' in sql
            assert args == (owner, 30, 990)
            return {'total':1000, 'items':json.dumps([{
                'snapshot':{'currency':'USD','id':str(UUID(int=1000))}, 'reviewed_at':None}])}
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        pool=SimpleNamespace(acquire=lambda:Connection()))))
    result = asyncio.run(routes.list_quotes(request, owner, page=34, page_size=30))
    assert result['total'] == 1000
    assert result['page'] == 34 and result['page_size'] == 30
    assert len(result['items']) == 1


def test_empty_history_keeps_actual_zero():
    class Connection:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def fetchrow(self, *args):
            return {'total':0,'items':[]}
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        pool=SimpleNamespace(acquire=lambda:Connection()))))
    assert asyncio.run(routes.list_quotes(request, UUID(int=1), 1, 30)) == {
        'items':[], 'total':0, 'page':1, 'page_size':30}
