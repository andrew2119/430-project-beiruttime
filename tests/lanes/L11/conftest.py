from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID
import httpx
import pytest_asyncio
from bt_bulkheads import DependencyClient
from bt_runtime.app import db
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings

pytest_plugins = ['bt_runtime.testing']
ROOT = next((path for path in Path(__file__).resolve().parents if (path / 'compose.yaml').is_file()), Path('/'))
BRAND = UUID('00000000-0011-4000-8000-000000000001')
DEALER = UUID('00000000-0011-4000-8000-000000000002')
BUYER = UUID('00000000-0011-4000-8000-000000000101')
OTHER = UUID('00000000-0011-4000-8000-000000000102')
STAFF = UUID('00000000-0011-4000-8000-000000000103')


class IdentityFixture:
    def __init__(self):
        self.unavailable = False
        self.status = 'active'
        self.requests = []
        self.revoked = False
        self.onboarded = True
        self.authenticated = True
        self.permissions = ['business.jobs.write', 'business.stock.write']
        self.kinds = {str(BRAND): 'brand', str(DEALER): 'dealer'}
        self.capabilities = {str(BRAND): ['sales', 'customization', 'servicing'], str(DEALER): ['sales', 'servicing']}

    def handle(self, request):
        self.requests.append(str(request.url))
        if self.unavailable:
            return httpx.Response(503)
        if request.url.path == '/internal/v1/principal':
            token = request.headers.get('Authorization', '')
            if self.revoked or token not in ('Bearer buyer', 'Bearer other', 'Bearer brand', 'Bearer dealer', 'Bearer cross'):
                return httpx.Response(401)
            staff = token in ('Bearer brand', 'Bearer dealer', 'Bearer cross')
            org = DEALER if token == 'Bearer dealer' else BRAND
            return httpx.Response(200, json={
                'actor': {'subject_id': str(STAFF if staff else OTHER if token=='Bearer other' else BUYER), 'session_id': 'fixture-session', 'organization_id': str(org) if staff else None},
                'roles': ['brand' if org == BRAND else 'dealer'] if staff else ['buyer'], 'permissions': [],
                'organizations': [str(org)] if staff else [],
                'organization_grants': [{'organization_id': str(DEALER if token=='Bearer cross' else org), 'roles':['brand' if org==BRAND else 'dealer'], 'permissions':self.permissions}] if staff else []})
        raw = request.url.path.split('/')[-1]
        if not request.url.path.startswith('/v1/businesses/') or raw not in self.kinds:
            return httpx.Response(404)
        return httpx.Response(200,json={
            'id':raw,'kind':self.kinds[raw],'state':self.status,'revision':1,
            'public_name':'Sample official brand' if raw==str(BRAND) else 'Sample official dealer',
            'capabilities':self.capabilities[raw],'sample':True,'platform_onboarded':self.onboarded,
            'authenticated_business':self.authenticated,'independent_watch_authentication_required':False})


@asynccontextmanager
async def module_stack(kind, database_url, database_owner_url, accounts_app=None, *, real_businesses=False):
    if real_businesses and accounts_app is None:
        raise ValueError('Real business authority requires an actual Identity app')
    # Container runner mounts the owning module; host runner can cover both domains.
    root = ROOT / ('services/service-operations/modules/directory' if kind=='directory' else 'services/catalog/modules/options/movement')
    if not root.exists():
        root = Path('/app/modules') / ('directory' if kind=='directory' else 'options/movement')
    # Image fixtures already migrate the complete service (including other lanes).
    # A focused module app must not replace that immutable ledger with a partial set.
    if ROOT != Path('/'):
        await db.migrate(database_owner_url, root)
    settings = Settings(database_url=database_url, service_name='service-operations' if kind=='directory' else 'catalog',modules_path=root)
    app = create_app(settings)
    app.state.pool = await db.create_pool(database_url,2)
    identity = IdentityFixture()
    accounts = httpx.AsyncClient(transport=httpx.ASGITransport(app=accounts_app),base_url='http://identity.fixture') if accounts_app else None
    async def authority(request):
        fixture_tokens = {'Bearer buyer','Bearer other','Bearer brand','Bearer dealer','Bearer cross'}
        current_actor = request.url.path == '/internal/v1/principal' and (
            real_businesses or request.headers.get('Authorization') not in fixture_tokens)
        current_business = real_businesses and request.url.path.startswith('/v1/businesses/')
        if accounts and not identity.unavailable and (current_actor or current_business):
            return await accounts.request(request.method,str(request.url),headers=dict(request.headers),content=request.content)
        return identity.handle(request)
    dependency = DependencyClient('identity','http://identity.fixture',transport=httpx.MockTransport(authority),failure_threshold=50)
    app.state.l11_identity = dependency
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://service.fixture') as client:
            yield client, app, identity
    finally:
        await dependency.aclose()
        if accounts:
            await accounts.aclose()
        await app.state.pool.close()


@pytest_asyncio.fixture
async def directory(database_url,database_owner_url):
    async with module_stack('directory',database_url,database_owner_url) as stack:
        yield stack


@pytest_asyncio.fixture
async def movement(database_url,database_owner_url):
    async with module_stack('movement',database_url,database_owner_url) as stack:
        yield stack
