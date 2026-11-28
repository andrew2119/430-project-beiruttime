from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import Response
from starlette.requests import Request

from bt_contracts_core.errors import AccessDenied, PublicError
from service_app import buyer_support


def ref(value):
    return UUID(int=value)


def request_for(deps, *, buyer='known-buyer'):
    return Request({'type': 'http', 'method': 'GET', 'path': '/', 'query_string': b'',
        'app': SimpleNamespace(state=SimpleNamespace(auction=SimpleNamespace(dependencies=deps))),
        'headers': [(b'authorization', b'Bearer trusted-communications'),
                    (b'x-buyer-authorization', f'Bearer {buyer}'.encode())]})


@pytest.mark.parametrize('state,order,financial,reason,status', [
    ('allocation_pending', None, None, 'allocation_pending', 200),
    ('closed', ref(5), 'unknown', 'payment_unknown', 200),
    ('closed', ref(5), 'released', None, 403),
    ('closed', ref(5), None, None, 503),
    ('allocation_denied', None, None, 'allocation_denied', 200),
    ('allocation_denied', None, None, None, 404),
    ('closed', ref(5), None, None, 404),
])
def test_held_result_is_bound_to_current_winner(monkeypatch, state, order, financial, reason, status):
    import asyncio

    buyer, auction, listing, watch = ref(1), ref(2), ref(3), ref(4)
    row = dict(id=auction, listing_id=listing, watch_id=watch, result_revision=2, currency='USD',
               seller_id=ref(6), seller_organization_id=ref(7), winner_id=buyer, state=state, order_id=order,
               held_since=datetime(2030, 1, 1, 12, tzinfo=timezone(timedelta(hours=2))),
               support_transition_retained=status != 404)

    def auth(request, allowed):
        assert allowed == {'communications'}
        assert request.headers['authorization'] == 'Bearer trusted-communications'

    async def principal(request):
        assert request.headers['authorization'] in ('Bearer known-buyer', 'Bearer different-buyer')
        assert 'x-buyer-authorization' not in request.headers
        actor = buyer if request.headers['authorization'].endswith('known-buyer') else ref(9)
        return SimpleNamespace(actor=SimpleNamespace(subject_id=actor, organization_id=None), roles=['buyer'], organizations=[],
                               permissions=['marketplace.activity.suspended'])

    async def facts(service, method, path, request, **options):
        assert (service, method, path) == ('orders', 'POST', '/internal/v2/auction-financial-facts')
        assert options['json'] == {'orders': [dict(order_id=str(order), auction_id=str(auction), watch_id=str(watch))]}
        if financial is None:
            return {'schema_version': 1, 'items': []}
        return {'schema_version': 1, 'items': [dict(order_id=str(order), auction_id=str(auction), watch_id=str(watch),
                                                  state=financial, revision=8)]}

    financial_source = AsyncMock(side_effect=facts)
    monkeypatch.setattr(buyer_support, 'service', auth)
    deps = SimpleNamespace(principal=principal, json=financial_source, service_headers=lambda *_: {'Authorization': 'Bearer auction'})

    class Database:
        async def fetchrow(self, sql, *args):
            assert 'c.created_at AS held_since' in sql and 'FROM l13_auction_support_outbox o' in sql
            assert 'o.result_revision=c.result_revision' in sql
            assert args == (auction,)
            return dict(row)

    @asynccontextmanager
    async def acquire():
        yield Database()

    def read(access='known-buyer', **options):
        request = request_for(deps, buyer=access)
        request.app.state.pool = SimpleNamespace(acquire=acquire)
        return asyncio.run(buyer_support.buyer_support(auction, request, response, **options))

    response = Response()
    if status == 200:
        payload = read()
        assert payload == dict(schema_version=1, auction_id=str(auction), listing_id=str(listing), watch_id=str(watch),
                               buyer_id=str(buyer), order_id=str(order) if order else None, result_revision=2,
                               financial_revision=8 if financial else None, reason=reason, held_since='2030-01-01T10:00:00Z')
        assert response.headers['cache-control'] == 'no-store'
    elif status == 403:
        with pytest.raises(AccessDenied):
            read()
    elif status == 404:
        with pytest.raises(AccessDenied):
            read()
        with pytest.raises(PublicError, match='support_history_missing') as exc:
            read(include_resolved=True)
        assert exc.value.status==404
        financial_source.assert_not_awaited()
    else:
        for include_resolved in (False, True):
            with pytest.raises(PublicError) as exc:
                read(include_resolved=include_resolved)
            assert exc.value.status == 503
    source_reads = financial_source.await_count
    with pytest.raises(AccessDenied):
        read('different-buyer', include_resolved=True)
    assert financial_source.await_count == source_reads
    if financial == 'released':
        history = read(include_resolved=True)
        assert history['reason'] is None and history['order_id'] == str(order)
        assert history['held_since'] == '2030-01-01T10:00:00Z' and history['financial_revision'] == 8
    if state == 'allocation_pending':
        order = ref(5)
        financial = 'released'
        row.update(state='closed', order_id=order, result_revision=3)
        history = read(include_resolved=True)
        assert history['auction_id'] == payload['auction_id'] and history['buyer_id'] == payload['buyer_id']
        assert history['held_since'] == payload['held_since'] and history['reason'] is None
        assert history['order_id'] == str(order) and history['result_revision'] == 3
