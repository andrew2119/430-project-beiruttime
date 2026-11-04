"""Disposable real Identity/Consent routes; browser business fixtures are explicit and optional.

These account/session and consent route proofs disable background dispatch in a temporary
Identity metadata copy; outbox intent stays pending and no message delivery is claimed.
Merged producer files are never edited.
"""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import httpx
from bt_bulkheads import DependencyClient
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from bt_runtime.app import db
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from .conftest import ROOT


@asynccontextmanager
async def accounts_routes(access):
    accounts_source = ROOT / 'services/identity/modules/accounts'
    source = accounts_source
    runtime = ROOT / 'services/identity/runtime'
    if not (accounts_source / 'routes.py').is_file() or not (runtime / 'service_app/identity.py').is_file():
        raise RuntimeError('Stage the published Accounts and Identity-local helper handoffs first')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    values = {'BT_AUTH_PRIVATE_KEY': private, 'BT_ALLOWED_WEB_ORIGINS': 'http://127.0.0.1:3111', 'BT_LOCAL_HTTP': '1'}
    prior = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    sys.path.insert(0, str(runtime))
    try:
        with TemporaryDirectory(prefix='l11-accounts-', dir=ROOT / '.venv') as temporary:
            module = Path(temporary) / 'accounts'
            shutil.copytree(source, module, ignore=shutil.ignore_patterns('__pycache__'))
            for metadata_path in module.rglob('module.json'):
                metadata = json.loads(metadata_path.read_text())
                metadata['workers'] = []
                metadata_path.write_text(json.dumps(metadata))
            await db.migrate(access.owner_url, module)
            settings = Settings(database_url=access.runtime_url, service_name='identity', modules_path=module, auth_public_key=public)
            app = create_app(settings)
            app.state.pool = await db.create_pool(access.runtime_url, 2)
            try:
                yield app
            finally:
                await app.state.pool.close()
    finally:
        sys.path.remove(str(runtime))
        for name, value in prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@asynccontextmanager
async def consent_routes(access, accounts_app):
    """Real merged Eligibility consent routes/SQL; canonical request outage is deliberate."""
    source = ROOT / 'services/eligibility/modules/consent'
    await db.migrate(access.owner_url, source)
    settings = Settings(database_url=access.runtime_url, service_name='eligibility', modules_path=source,
        auth_public_key=accounts_app.state.settings.auth_public_key)
    app = create_app(settings)
    app.state.pool = await db.create_pool(access.runtime_url, 2)
    app.state.identity = DependencyClient('identity', 'http://identity.proof', timeout=0.5, concurrency=2,
        transport=httpx.ASGITransport(app=accounts_app))
    app.state.catalog = DependencyClient('catalog', 'http://127.0.0.1:1', timeout=0.3, concurrency=1)
    try:
        yield app
    finally:
        await app.state.catalog.aclose()
        await app.state.identity.aclose()
        await app.state.pool.close()
