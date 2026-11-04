import json
from uuid import uuid4
import pytest
import httpx
from bt_bulkheads import DependencyClient
from fastapi.testclient import TestClient
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.files import ScopedFiles
from bt_runtime.principal import CurrentPrincipal, OrganizationGrant, current_principal, require_scope
from bt_contracts_core.models import Actor, Money
from bt_contracts_core.errors import AccessDenied, PublicError


def test_body_budget_returns_standard_error_without_storage():
    app=create_app(Settings(database_url='postgresql://unused/unused', request_body_limit=65536))
    client=TestClient(app)
    try:
        result=client.post('/missing',content=b'x'*65537,headers={'X-Request-ID':'body-proof'})
        assert result.status_code==413
        assert result.json()['error']['code']=='body_too_large'
        assert result.headers['X-Request-ID']=='body-proof'
        assert client.get('/health/ready').status_code==503
    finally:
        client.close()


def test_pure_module_hooks_are_discovered_and_async_hooks_refused(tmp_path):
    root=tmp_path/'proxy'
    root.mkdir()
    data={'version':1,'id':'L06.proxy-proof','hooks':{'auction.proxy.v1':'proxy.py:calculate'}}
    (root/'module.json').write_text(json.dumps(data))
    (root/'proxy.py').write_text('def calculate(snapshot): return snapshot+1\n')
    app=create_app(Settings(database_url='postgresql://unused/unused', modules_path=tmp_path))
    assert app.state.hooks['auction.proxy.v1'](2)==3
    other=tmp_path/'async'
    other.mkdir()
    (other/'module.json').write_text(json.dumps({'version':1,'id':'L06.async-proof','hooks':{'auction.other.v1':'proxy.py:calculate'}}))
    (other/'proxy.py').write_text('async def calculate(snapshot): return snapshot\n')
    with pytest.raises(ValueError, match='asynchronous pure hook'):
        create_app(Settings(database_url='postgresql://unused/unused',modules_path=tmp_path))


@pytest.mark.asyncio
async def test_private_file_denial_precedes_storage_reads():
    class Store:
        read_called=False
        async def read(self, blob_id, *, max_bytes):
            self.read_called=True
            return b'private'
    async def denied(principal, resource):
        raise AccessDenied('denied')
    store=Store()
    principal=CurrentPrincipal(actor=Actor(subject_id=uuid4(), session_id='proof'))
    with pytest.raises(PermissionError):
        await ScopedFiles(store,denied).read(principal,uuid4())
    assert not store.read_called


def test_public_errors_preserve_codes_and_redact_internal_denials():
    app=create_app(Settings(database_url='postgresql://unused/unused'))
    @app.get('/v1/proof/conflict')
    async def conflict():
        raise PublicError('revision_conflict','The revision changed.',status=409,details={'code':'safe-nested-code','minimum':Money(amount='12.50',currency='USD')})
    @app.get('/v1/proof/denied')
    async def denied():
        raise AccessDenied('synthetic-internal-marker')
    client=TestClient(app)
    try:
        conflict=client.get('/v1/proof/conflict',headers={'X-Request-ID':'error-proof'})
        assert conflict.status_code==409
        assert conflict.json()['error']['code']=='revision_conflict'
        assert conflict.json()['error']['details']['minimum']=={'amount':'12.50','currency':'USD'}
        denied=client.get('/v1/proof/denied')
        assert denied.status_code==403
        assert 'synthetic-internal-marker' not in denied.text
    finally:
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(401, 'unauthorized'), (403, 'forbidden')])
async def test_identity_authentication_and_permission_denials_stay_distinct(status, code):
    def identity_response(request):
        assert request.headers['Authorization'] == 'Bearer synthetic-expired-proof'
        return httpx.Response(status, json={'internal': 'synthetic-private-identity-marker'})
    identity=DependencyClient('identity','http://identity.test',transport=httpx.MockTransport(identity_response))
    app=create_app(Settings(database_url='postgresql://unused/unused'))
    @app.get('/v1/proof/principal')
    async def principal():
        return await current_principal(identity,'synthetic-expired-proof','principal-proof')
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://domain.test') as client:
            response=await client.get('/v1/proof/principal',headers={'X-Request-ID':'principal-proof'})
        assert response.status_code==status
        assert response.json()['error']['code']==code
        assert response.json()['error']['request_id']=='principal-proof'
        assert response.headers['X-Request-ID']=='principal-proof'
        assert 'synthetic-private-identity-marker' not in response.text
    finally:
        await identity.aclose()


def test_organization_permissions_do_not_leak_across_memberships():
    first, second = uuid4(), uuid4()
    principal=CurrentPrincipal(actor=Actor(subject_id=uuid4(),organization_id=first,session_id='proof'),
        organizations=[first,second],permissions=['catalog.publish'],
        organization_grants=[OrganizationGrant(organization_id=first,permissions=['catalog.publish'])])
    require_scope(principal,'catalog.publish',first)
    with pytest.raises(PermissionError):
        require_scope(principal,'catalog.publish',second)
    with pytest.raises(PermissionError):
        require_scope(principal,'identity.review')
