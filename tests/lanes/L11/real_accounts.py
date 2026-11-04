"""Disposable real Accounts HTTP routes; business/staff authority is still a separate V1 fixture.

The published Accounts handoff omits its dispatcher implementation. This route proof
therefore disables that absent worker in a temporary metadata copy; outbox intent stays
pending and no message delivery is claimed. Published producer files are never edited.
"""
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from bt_runtime.app import db
from bt_runtime.app.main import create_app
from bt_runtime.app.settings import Settings
from .conftest import ROOT


@asynccontextmanager
async def accounts_routes(access):
    source = ROOT / 'services/identity/modules/accounts'
    runtime = ROOT / 'services/identity/runtime'
    if not (source / 'routes.py').is_file() or not (runtime / 'service_app/identity.py').is_file():
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
            metadata = json.loads((module / 'module.json').read_text())
            metadata['workers'] = []
            (module / 'module.json').write_text(json.dumps(metadata))
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
