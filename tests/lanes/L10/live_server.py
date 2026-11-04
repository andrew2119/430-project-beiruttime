"""Isolated connected browser proof using published owning-service source, never transport fixtures.

Requires uncommitted L01/L02/L11 source handoffs mounted at /proof/repository.
Each service uses a separate disposable database and restricted role. Only the
proof operator grant is provisioned directly; accounts, businesses, memberships,
directory profiles, options and buyer commands use their real HTTP APIs.
"""
import asyncio
import os
import secrets
import signal
from contextlib import AsyncExitStack, asynccontextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from uuid import UUID, uuid4
import httpx
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from bt_runtime.app.db import migrate
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from bt_runtime.testing import database_access

ROOT = Path('/proof/repository')
ORIGIN = 'http://localhost:3110'


class ProofServer(uvicorn.Server):
    # Multiple services share this proof process; one outer shutdown owns DB cleanup.
    def capture_signals(self):
        return nullcontext()


async def accepted(client, method, path, **kwargs):
    response = await client.request(method, path, **kwargs)
    if response.status_code not in {200, 201}:
        raise RuntimeError(f'{method} {path}: {response.status_code} {response.text[:200]}')
    return response.json()


async def main():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                               serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                          serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    os.environ.update(BT_AUTH_PRIVATE_KEY=private, BT_LOCAL_HTTP='1', BT_ALLOWED_WEB_ORIGINS=ORIGIN,
                      IDENTITY_API_URL='http://127.0.0.1:8121', SERVICE_OPERATIONS_API_URL='http://127.0.0.1:8129')
    async with AsyncExitStack() as stack:
        temporary = stack.enter_context(TemporaryDirectory())
        applications = []
        for name, path, port in [('identity', 'services/identity/modules', 8121),
                                  ('service-operations', 'services/service-operations/modules', 8129),
                                  ('catalog', 'services/catalog/modules/options', 8000)]:
            # Reuse the foundation's isolated database/role cleanup, not ordinary domain databases.
            directory = Path(temporary) / name
            directory.mkdir()
            access = await stack.enter_async_context(asynccontextmanager(database_access.__wrapped__)(
                SimpleNamespace(param='core-only'), directory))
            modules = ROOT / path
            await migrate(access.owner_url, modules)
            app = create_app(Settings(service_name=name, database_url=access.runtime_url,
                modules_path=modules, auth_public_key=public))
            applications.append((app, port))
        servers = [ProofServer(uvicorn.Config(app, host='0.0.0.0', port=port, access_log=False))
                   for app, port in applications]
        def shutdown():
            for server in servers:
                server.should_exit = True
        loop = asyncio.get_running_loop()
        for selected_signal in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(selected_signal, shutdown)
        tasks = [asyncio.create_task(server.serve()) for server in servers]
        try:
            for _ in range(200):
                if all(server.started for server in servers):
                    break
                if any(task.done() for task in tasks):
                    raise RuntimeError('Owning service failed to start')
                await asyncio.sleep(.05)
            else:
                raise RuntimeError('Owning services did not become ready')
            async with httpx.AsyncClient(base_url='http://127.0.0.1:8121', headers={'Origin': ORIGIN}, timeout=10) as identity:
                password = secrets.token_urlsafe(24)
                operator = await accepted(identity, 'POST', '/v1/accounts/register',
                    headers={'Idempotency-Key': uuid4().hex}, json={'email': 'operator@example.test',
                        'password': password, 'display_name': 'Sample operator'})
                staff = await accepted(identity, 'POST', '/v1/accounts/register',
                    headers={'Idempotency-Key': uuid4().hex}, json={'email': 'staff@example.test',
                        'password': password, 'display_name': 'Sample staff'})
                async with applications[0][0].state.pool.acquire() as tx:
                    await tx.execute("""INSERT INTO identity_access_grants(id,subject_id,role,permissions)
                        VALUES($1,$2,'operator',ARRAY['identity.businesses.manage','identity.membership.manage'])""",
                        uuid4(), UUID(operator['account']['id']))
                authority = {'Authorization': 'Bearer '+operator['access_token'], 'Idempotency-Key': uuid4().hex}
                business = await accepted(identity, 'POST', '/v1/businesses', headers=authority,
                    json={'legal_name': 'Sample Cedar Atelier SAL', 'public_name': 'Sample Cedar Atelier',
                        'kind': 'brand', 'capabilities': ['customization'], 'sample': True,
                        'assurance_reference': 'SAMPLE-PROOF-COMMUNICATION',
                        'reason': 'Labeled isolated proof business'})
                await accepted(identity, 'POST', '/v1/memberships',
                    headers={**authority, 'Idempotency-Key': uuid4().hex}, json={'business_id': business['id'],
                        'subject_id': staff['account']['id'], 'capabilities': ['business.jobs.write'],
                        'qualifications': ['Sample intake training'], 'intervention_scope': 'Sample customization only',
                        'reason': 'Explicit isolated proof staff authorization'})
                # Membership changes revoke old sessions; obtain current staff authority through login.
                staff = await accepted(identity, 'POST', '/v1/accounts/login',
                    json={'email': 'staff@example.test', 'password': password})
                staff_headers = {'Authorization': 'Bearer '+staff['access_token'], 'Idempotency-Key': uuid4().hex}
                async with httpx.AsyncClient(base_url='http://127.0.0.1:8129', timeout=10) as directory:
                    await accepted(directory, 'PUT', '/v1/directory/businesses/'+business['id'], headers=staff_headers,
                        json={'expected_revision': 0, 'capabilities': ['customization'], 'contact': 'Sample contact',
                            'visit_en': 'By request', 'visit_ar': 'حسب الطلب', 'scope_en': 'Sample customization',
                            'scope_ar': 'تخصيص نموذجي', 'published': True})
                import json
                fixture = json.loads((ROOT / 'packages/contracts-catalog/options/fixtures/options.v1.json').read_text())
                async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', timeout=10) as catalog:
                    for option in fixture['options']:
                        await accepted(catalog, 'PUT', f"/v1/brand-options/brands/{business['id']}/{option['kind']}/{option['id']}",
                            headers={**staff_headers, 'Idempotency-Key': uuid4().hex}, json=option['definition'])
                # Browser registers its own buyer through the actual account screen; no credential is exposed here.
                print('L10_LIVE_READY brand='+business['id'], flush=True)
            completed, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in completed:
                task.result()
        finally:
            for server in servers:
                server.should_exit = True
            await asyncio.gather(*tasks, return_exceptions=True)
            for selected_signal in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(selected_signal)
    print('L10_LIVE_CLEANED three isolated databases and their roles', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
