import asyncio
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from bt_contracts_core.errors import AccessDenied, PublicError
from service_app.dependencies import Dependencies


@pytest.mark.parametrize('answer,code', [
    ('held', None), ('suspended', 'bid_permission_required'), ('wrong_digest', 'admission_unavailable'),
    ('short', 'admission_unavailable'), ('late', 'admission_unavailable'), ('upstream_denied', 'admission_unavailable'),
])
def test_bid_fence_binds_signed_actor_session_and_deadline(answer, code):
    pytest.importorskip('bt_contracts.identity.marketplace_admission.v1')
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    deadline = now + timedelta(milliseconds=2800)
    cutoff_calls = []
    subject, session = UUID(int=1), UUID(int=2)
    principal = SimpleNamespace(actor=SimpleNamespace(subject_id=subject, session_id=str(session)))
    request = SimpleNamespace()

    async def fetchval(sql, *args):
        if 'transaction_timeout' in sql:
            cutoff_calls.append(sql)
            return deadline
        assert sql == 'SELECT clock_timestamp()' and cutoff_calls
        return deadline if answer == 'late' else now

    async def peer(name, method, path, actual, *, headers, content):
        assert cutoff_calls and actual is request
        assert (name, method, path) == ('identity', 'POST', '/internal/v1/marketplace-admission')
        assert headers == {'Authorization': 'Bearer auction-for-identity', 'Content-Type': 'application/json'}
        assert json.loads(content) == {'actor_id': str(subject), 'session_id': str(session),
                                       'hold_until': (deadline + timedelta(seconds=1)).isoformat()}
        if answer == 'upstream_denied':
            raise AccessDenied('Upstream refused')
        return {'status': 'suspended' if answer == 'suspended' else 'held',
                'binding_hash': '0' * 64 if answer == 'wrong_digest' else sha256(content).hexdigest(),
                'held_until': (deadline if answer == 'short' else deadline + timedelta(seconds=1)).isoformat()}

    deps = Dependencies(clients={'identity': object()})
    deps.service_headers = lambda _, audience: {'Authorization': 'Bearer auction-for-' + audience}
    deps.json = AsyncMock(side_effect=peer)
    txn = SimpleNamespace(fetchval=fetchval)
    if code:
        with pytest.raises(PublicError) as error:
            asyncio.run(deps.bid_admission(request, txn, principal))
        assert error.value.code == code and error.value.status == (403 if answer == 'suspended' else 503)
    else:
        asyncio.run(deps.bid_admission(request, txn, principal))
    deps.json.assert_awaited_once()
