"""Real HTTP/JWT boundary with explicit upstream transport fixtures, not demo auth."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from bt_bulkheads import DependencyClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings

ROOT = next((p for p in Path(__file__).resolve().parents if (p / 'services').is_dir()), Path('/app'))
# Keep this module's JWT proofs independent of other Communications extensions.
MODULES = ROOT / 'services/communications/modules/buyer-workspace'
if not MODULES.exists():
    MODULES = Path('/app/modules/buyer-workspace')
OWNER = '00000000-0000-0000-0000-000000000006'
OTHER = '00000000-0000-0000-0000-000000000007'


@pytest.fixture(scope='module')
def signing_keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return private, public


def token(private, **changes):
    now = datetime.now(timezone.utc)
    return jwt.encode({'sub': OWNER, 'sid': 'lineage-6', 'iss': 'beirut-time-identity', 'aud': 'beirut-time',
                       'iat': now, 'exp': now + timedelta(minutes=5), 'type': 'access', **changes}, private, algorithm='RS256')


@asynccontextmanager
async def boundary(public, *, subject=OWNER, lineage='lineage-6', roles=None, organization=None, identity_status=200):
    calls = []
    principal = {'actor': {'subject_id': subject, 'session_id': lineage, 'organization_id': organization},
                 'roles': roles if roles is not None else ['buyer']}
    def upstream(name):
        def handle(request):
            calls.append(name)
            assert request.headers['x-request-id'] == 'request-6'
            assert request.headers['authorization'].startswith('Bearer ')
            return httpx.Response(identity_status if name == 'identity' else 200,
                                  json=principal if name == 'identity' else {'items': [], 'next_cursor': None})
        return DependencyClient(name, 'http://' + name, transport=httpx.MockTransport(handle))
    clients = {name: upstream(name) for name in ['identity', 'auction', 'orders']}
    app = create_app(Settings(service_name='communications', database_url='postgresql://unused/unused',
                              modules_path=MODULES, auth_public_key=public))
    app.state.l06_workspace_clients = clients
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://communications') as http:
            yield http, calls
    finally:
        for client in clients.values():
            await client.aclose()


@pytest.mark.asyncio
async def test_current_buyer_session_reaches_only_owner_private_sources(signing_keys):
    private, public = signing_keys
    async with boundary(public) as (http, calls):
        response = await http.get('/v1/buyer-workspace', headers={'Authorization': 'Bearer ' + token(private), 'X-Request-ID': 'request-6'})
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert calls == ['identity', 'auction', 'orders']
    assert response.json()['bids']['state'] == response.json()['reservations']['state'] == 'available'
    assert 'Bearer' not in response.text and OWNER not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'subject': OTHER}, {'lineage': 'revoked-lineage'}, {'roles': ['operator']}, {'roles': ['private_seller']}, {'organization': OTHER}])
async def test_signature_never_substitutes_for_current_subject_lineage_or_role(signing_keys, changes):
    private, public = signing_keys
    async with boundary(public, **changes) as (http, calls):
        response = await http.get('/v1/buyer-workspace', headers={'Authorization': 'Bearer ' + token(private), 'X-Request-ID': 'request-6'})
    assert response.status_code == 403 and response.json()['error']['code'] == 'forbidden'
    assert calls == ['identity']
    assert OTHER not in response.text and 'revoked-lineage' not in response.text


@pytest.mark.asyncio
async def test_unavailable_identity_prevents_all_private_upstream_reads(signing_keys):
    private, public = signing_keys
    async with boundary(public, identity_status=503) as (http, calls):
        response = await http.get('/v1/buyer-workspace', headers={'Authorization': 'Bearer ' + token(private), 'X-Request-ID': 'request-6'})
    assert response.status_code == 503 and calls == ['identity']


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [401, 403])
async def test_current_identity_denial_is_preserved_before_source_reads(signing_keys, status):
    private, public = signing_keys
    async with boundary(public, identity_status=status) as (http, calls):
        response = await http.get('/v1/buyer-workspace', headers={'Authorization': 'Bearer ' + token(private), 'X-Request-ID': 'request-6'})
    assert response.status_code == status and calls == ['identity']
    assert response.json()['error']['code'] == ('unauthorized' if status == 401 else 'forbidden')


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [{'roles': 'buyer'}, {'subject': 'not-a-subject-uuid'}])
async def test_malformed_identity_success_is_unavailable_not_authority(signing_keys, changes):
    private, public = signing_keys
    async with boundary(public, **changes) as (http, calls):
        response = await http.get('/v1/buyer-workspace', headers={'Authorization': 'Bearer ' + token(private), 'X-Request-ID': 'request-6'})
    assert response.status_code == 503 and calls == ['identity']
    assert response.json()['error']['code'] == 'unavailable'


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['missing', 'expired', 'wrong_audience', 'wrong_type'])
async def test_invalid_token_fails_before_any_dependency(signing_keys, kind):
    private, public = signing_keys
    changes = {'expired': {'exp': datetime.now(timezone.utc) - timedelta(seconds=10)},
               'wrong_audience': {'aud': 'another-service'}, 'wrong_type': {'type': 'service'}}
    headers = {'X-Request-ID': 'request-6'}
    if kind != 'missing':
        headers['Authorization'] = 'Bearer ' + token(private, **changes[kind])
    async with boundary(public) as (http, calls):
        response = await http.get('/v1/buyer-workspace', headers=headers)
    assert response.status_code == 401 and calls == []
    assert response.json()['error']['code'] == 'unauthorized'
