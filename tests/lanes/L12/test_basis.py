"""Synthetic historical read fixtures; no new auction purchase is admitted."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from starlette.datastructures import Headers
from bt_contracts_core.errors import AccessDenied, PublicError
from bt_runtime.modules import discover


def basis():
    return next(m for m in discover(Path('services/auction/modules')) if m.id == 'L12.prebid-buy-now').load('basis.py:quote_basis')


class Reader:
    def __init__(self, row): self.row = row
    def acquire(self): return self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def fetchrow(self, sql, auction, buyer):
        return self.row if (auction, buyer) == (self.row['auction_id'], self.row['subject_id']) else None


def fixture():
    auction, buyer, quote, watch, listing = [uuid4() for _ in range(5)]
    row = {'auction_id': auction, 'subject_id': buyer, 'admission_revision': 1, 'current_revision': 2,
        'watch_id': watch, 'listing_id': listing, 'mode': 'prebid_pending', 'status': 'pending',
        'currency': 'USD', 'buy_now_minor': 500000, 'created_at': datetime.now(timezone.utc)}
    row['allocation'] = {'source_id': str(auction), 'watch_id': str(watch), 'listing_id': str(listing),
        'listing_revision': 1, 'quote_id': str(quote), 'quote_revision': 1, 'currency': 'USD', 'total_minor': 515000}
    settings = SimpleNamespace(service_auth_public_key='', auth_issuer='fixture')
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings, pool=Reader(row))), headers=Headers())
    return request, row, quote


def auth(request, *, subject='pricing', kind='service', audience='auction'):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    settings = request.app.state.settings
    settings.service_auth_public_key = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    now = datetime.now(timezone.utc)
    token = jwt.encode({'sub': subject, 'type': kind, 'aud': audience, 'iss': settings.auth_issuer,
        'iat': now, 'exp': now+timedelta(minutes=1)}, key, algorithm='RS256')
    request.headers = Headers({'Authorization': 'Bearer '+token})


@pytest.mark.asyncio
async def test_historical_basis_binds_admission_not_current_revision(monkeypatch):
    handler = basis()
    monkeypatch.setitem(handler.__globals__, 'get_kernel', lambda: object())
    request, row, quote = fixture()
    with pytest.raises(PublicError): await handler(row['auction_id'], quote, row['subject_id'], request)
    auth(request)
    value = await handler(row['auction_id'], quote, row['subject_id'], request)
    assert value['admission_revision'] == 1 and value['current_revision'] == 2
    assert value['price_minor'] == 500000 and value['total_minor'] == 515000
    for wrong_quote, wrong_buyer in [(uuid4(), row['subject_id']), (quote, uuid4())]:
        with pytest.raises(PublicError) as error: await handler(row['auction_id'], wrong_quote, wrong_buyer, request)
        assert error.value.code == 'not_found'
    row.update(mode='prebid_reserved', current_revision=3)
    assert (await handler(row['auction_id'], quote, row['subject_id'], request))['admission_revision'] == 1
    row['admission_revision'] = None
    with pytest.raises(PublicError) as error: await handler(row['auction_id'], quote, row['subject_id'], request)
    assert error.value.code == 'source_changed'


@pytest.mark.parametrize('overrides,error', [({'subject': 'catalog'}, AccessDenied), ({'kind': 'access'}, AccessDenied), ({'audience': 'orders'}, HTTPException)])
@pytest.mark.asyncio
async def test_historical_basis_denies_wrong_current_service_scope(overrides, error):
    request, row, quote = fixture()
    auth(request, **overrides)
    with pytest.raises(error): await basis()(row['auction_id'], quote, row['subject_id'], request)
