import asyncio
import json
import time
from pathlib import Path
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from pydantic import ValidationError
from bt_runtime.auth import TokenVerifier, InvalidToken
from bt_bulkheads import DependencyClient
from bt_contracts_core.models import EventEnvelope
from bt_contracts_core.errors import ErrorEnvelope


@pytest.mark.asyncio
async def test_breaker_and_dependency_isolation():
    async def fail(request):
        return httpx.Response(503)
    bad = DependencyClient('bad', 'http://bad', failure_threshold=2, cooldown=.02,
                           transport=httpx.MockTransport(fail))
    good = DependencyClient('good', 'http://good', transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    try:
        assert (await bad.request('GET','/')).reason == 'upstream'
        assert (await bad.request('GET','/')).reason == 'upstream'
        assert (await bad.request('GET','/')).reason == 'circuit_open'
        assert (await good.request('GET','/')).status_code == 200
        await asyncio.sleep(.03)
        assert (await bad.request('GET','/')).reason == 'upstream'
    finally:
        await bad.aclose()
        await good.aclose()


@pytest.mark.asyncio
async def test_saturation_timeout_and_cancellation_release_slots():
    started, release = asyncio.Event(), asyncio.Event()
    async def stall(request):
        started.set()
        await release.wait()
        return httpx.Response(200)
    client = DependencyClient('slow', 'http://slow', concurrency=1, timeout=.05,
                              transport=httpx.MockTransport(stall))
    try:
        first = asyncio.create_task(client.request('GET','/'))
        await started.wait()
        assert (await client.request('GET','/')).reason == 'saturated'
        assert (await first).reason == 'timeout'
        second = asyncio.create_task(client.request('GET','/'))
        await asyncio.sleep(0)
        second.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second
        release.set()
        assert (await client.request('GET','/')).status_code == 200
    finally:
        await client.aclose()


def test_token_verification_is_fail_closed():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    verifier = TokenVerifier(public.decode(), 'identity', 'beirut-time')
    claims = dict(sub='demo', sid='demo-session', iss='identity', aud='beirut-time', type='access',
                  iat=int(time.time()), exp=int(time.time())+60)
    def sign(c):
        return jwt.encode(c, private, algorithm='RS256')
    assert verifier.verify(sign(claims)).subject == 'demo'
    for patch in [dict(aud='other'), dict(type='refresh'), dict(exp=1), dict(sid='')]:
        with pytest.raises(InvalidToken):
            verifier.verify(sign({**claims, **patch}))
    with pytest.raises(InvalidToken):
        verifier.verify(jwt.encode(claims, 'not-a-public-key', algorithm='HS256'))


def test_contract_fixtures():
    root = Path('/contracts') if Path('/contracts').exists() else Path(__file__).resolve().parents[3] / 'contracts'
    EventEnvelope.model_validate_json((root / 'fixtures/event.v1.json').read_text())
    ErrorEnvelope.model_validate_json((root / 'fixtures/error.v1.json').read_text())
    with pytest.raises(ValidationError):
        EventEnvelope(type='unversioned', source='identity', subject='x', request_id='proof')
    with pytest.raises(ValidationError):
        EventEnvelope.model_validate({**json.loads((root / 'fixtures/event.v1.json').read_text()), 'time': '2026-11-04T00:00:00'})
