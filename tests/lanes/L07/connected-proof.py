"""Own disposable connected proof; never reconfigure a shared domain container.

Runs the actual published Identity image plus owned Pricing/Communications images,
with three unique restricted PostgreSQL databases. Only this test project is stopped.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
STATE = Path(__file__).resolve().parent / '.runtime' / 'connected'
PROJECT = 'bt-l07-proof'
NETWORK = 'beirut-time_default'
IMAGES = {'pricing': 'beirut-time/l07-pricing:proof', 'communications': 'beirut-time/l07-communications:proof'}


def call(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def config():
    return json.loads(subprocess.check_output([str(ROOT / 'infra/foundation/compose.sh'), 'config', '--format', 'json'], cwd=ROOT))


def helper(code, image, admin):
    return call('docker', 'run', '--rm', '-i', '--user', f'{os.getuid()}:{os.getgid()}', '--network', NETWORK, '--entrypoint', 'python',
        '-v', str(STATE) + ':/proof', '-e', 'TEST_DATABASE_ADMIN_URL', image, '-',
        input=code, text=True, env={**os.environ, 'TEST_DATABASE_ADMIN_URL': admin})


PROVISION = r"""
import asyncio,json,os,re,secrets,time
from pathlib import Path
from uuid import uuid4
import asyncpg,jwt
from urllib.parse import quote
async def run():
 admin=await asyncpg.connect(os.environ['TEST_DATABASE_ADMIN_URL'])
 state={}
 try:
  for service in ('identity','pricing','communications'):
   name='bt_test_l07_'+uuid4().hex[:16]
   owner=name+'_owner'; runtime=name
   op,rp=secrets.token_urlsafe(24),secrets.token_urlsafe(24)
   async with admin.transaction():
    for role,password in ((owner,op),(runtime,rp)):
     await admin.execute(await admin.fetchval("SELECT format('CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE',$1::text,$2::text)",role,password))
   await admin.execute(f'CREATE DATABASE "{name}" OWNER "{owner}"')
   root=os.environ['TEST_DATABASE_ADMIN_URL'].rsplit('/',1)[0]+'/'+name
   setup=await asyncpg.connect(root)
   try:
    await setup.execute(f'''REVOKE ALL ON DATABASE "{name}" FROM PUBLIC;
     GRANT CONNECT ON DATABASE "{name}" TO "{runtime}";
     REVOKE ALL ON SCHEMA public FROM PUBLIC;
     ALTER SCHEMA public OWNER TO "{owner}";
     GRANT USAGE ON SCHEMA public TO "{runtime}";
     ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO "{runtime}";
     ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO "{runtime}";''')
   finally: await setup.close()
   state[service]={'name':name,'owner_url':f'postgresql://{owner}:{quote(op)}@postgres:5432/{name}', 'runtime_url':f'postgresql://{runtime}:{quote(rp)}@postgres:5432/{name}'}
   Path('/proof/databases.json').write_text(json.dumps(state))
  key=Path('/proof/events.pem').read_text()
  token=jwt.encode({'sub':'pricing','type':'service','aud':'communications','iss':'beirut-time-identity','iat':int(time.time()),'exp':int(time.time())+21600},key,algorithm='RS256')
  Path('/proof/service-token').write_text(token)
 finally: await admin.close()
asyncio.run(run())
"""

CLEANUP = r'''
import asyncio,json,os,re
from pathlib import Path
import asyncpg
async def run():
 admin=await asyncpg.connect(os.environ['TEST_DATABASE_ADMIN_URL'])
 try:
  for entry in json.loads(Path('/proof/databases.json').read_text()).values():
   name=entry['name']
   if not re.fullmatch(r'bt_test_l07_[a-f0-9]{16}',name): raise RuntimeError('Not an owned disposable database')
   await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
   await admin.execute(f'DROP ROLE IF EXISTS "{name}"')
   await admin.execute(f'DROP ROLE IF EXISTS "{name}_owner"')
 finally: await admin.close()
asyncio.run(run())
'''


def main():
    os.chdir(ROOT)
    STATE.mkdir(parents=True, exist_ok=True)
    STATE.chmod(0o700)
    admin = 'postgresql://postgres:' + config()['services']['postgres']['environment']['POSTGRES_PASSWORD'] + '@postgres:5432/postgres'
    command = sys.argv[1] if len(sys.argv) > 1 else 'start'
    compose = ['docker', 'compose', '-p', PROJECT, '-f', str(STATE / 'compose.json')]
    if command == 'stop':
        if (STATE / 'compose.json').exists():
            call(*compose, 'down', '--remove-orphans')
        if (STATE / 'databases.json').exists():
            helper(CLEANUP, IMAGES['pricing'], admin)
            (STATE / 'databases.json').unlink()
        print('Stopped only the L07 proof project and removed its generated disposable databases.')
        return
    if command == 'refresh':
        if not (STATE / 'databases.json').exists():
            raise SystemExit('No owned connected proof exists')
        databases = json.loads((STATE / 'databases.json').read_text())
        for service, image in IMAGES.items():
            call('docker', 'build', '-f', f'services/{service}/runtime/Dockerfile', '-t', image, '.')
            call('docker', 'run', '--rm', '--network', NETWORK, '-e', 'BT_DATABASE_URL', '-e', 'BT_SERVICE_NAME', image,
                'python', '-m', 'service_app.migrate', env={**os.environ, 'BT_DATABASE_URL': databases[service]['owner_url'], 'BT_SERVICE_NAME': service})
        definition = json.loads((STATE / 'compose.json').read_text())
        definition['services']['l07-pricing']['environment']['BT_PRICING_EVENT_PRIVATE_KEY'] = (STATE / 'events.pem').read_text()
        (STATE / 'compose.json').write_text(json.dumps(definition))
        call(*compose, 'up', '-d', '--no-deps', '--wait', 'l07-pricing', 'l07-communications')
        print('Updated only the owned L07 proof runtimes; acknowledged data and Identity session database preserved.')
        return
    if command != 'start':
        raise SystemExit('Use start, refresh or stop')
    if (STATE / 'databases.json').exists():
        raise SystemExit('An owned proof exists; stop it before provisioning another.')
    for service, image in IMAGES.items():
        call('docker', 'build', '-f', f'services/{service}/runtime/Dockerfile', '-t', image, '.')
    identity_image = subprocess.check_output(['docker', 'image', 'inspect', 'beirut-time/identity:local', '-f', '{{.Id}}'], text=True).strip()
    for name in ('auth', 'events'):
        call('openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(STATE / (name + '.pem')), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        call('openssl', 'pkey', '-in', str(STATE / (name + '.pem')), '-pubout', '-out', str(STATE / (name + '-public.pem')), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    helper(PROVISION, IMAGES['pricing'], admin)
    databases = json.loads((STATE / 'databases.json').read_text())
    images = {**IMAGES, 'identity': identity_image}
    services = {}
    ports = {'identity': 18101, 'pricing': 18104, 'communications': 18108}
    for service, image in images.items():
        environment = {'BT_DATABASE_URL': databases[service]['runtime_url'], 'BT_SERVICE_NAME': service,
            'BT_AUTH_ISSUER': 'beirut-time-identity', 'BT_AUTH_AUDIENCE': 'beirut-time',
            'BT_AUTH_PUBLIC_KEY': (STATE / 'auth-public.pem').read_text(),
            'BT_SERVICE_AUTH_PUBLIC_KEY': (STATE / 'events-public.pem').read_text(),
            'IDENTITY_API_URL': 'http://l07-identity:8000', 'PRICING_API_URL': 'http://l07-pricing:8000',
            'COMMUNICATIONS_API_URL': 'http://l07-communications:8000', 'ORDERS_API_URL': 'http://l07-unavailable-orders:8000'}
        if service == 'identity':
            environment.update({'BT_AUTH_PRIVATE_KEY': (STATE / 'auth.pem').read_text(), 'BT_EVENT_PRIVATE_KEY': (STATE / 'events.pem').read_text(),
                'BT_WEB_ORIGIN': 'http://localhost:3077', 'BT_ALLOWED_WEB_ORIGINS': 'http://localhost:3077', 'BT_LOCAL_HTTP': '1'})
        if service == 'pricing':
            environment['BT_COMMUNICATIONS_SERVICE_TOKEN'] = (STATE / 'service-token').read_text()
            environment['BT_PRICING_EVENT_PRIVATE_KEY'] = (STATE / 'events.pem').read_text()
        migration_env = {**os.environ, 'BT_DATABASE_URL': databases[service]['owner_url'], 'BT_SERVICE_NAME': service}
        call('docker', 'run', '--rm', '--network', NETWORK, '-e', 'BT_DATABASE_URL', '-e', 'BT_SERVICE_NAME', image,
             'python', '-m', 'service_app.migrate', env=migration_env)
        services['l07-' + service] = {'image': image, 'environment': environment, 'networks': ['shared'],
            'ports': [f'127.0.0.1:{ports[service]}:8000'], 'read_only': True, 'tmpfs': ['/tmp'],
            'mem_limit': '256m', 'cpus': 0.5, 'pids_limit': 128, 'cap_drop': ['ALL'], 'security_opt': ['no-new-privileges:true']}
    (STATE / 'compose.json').write_text(json.dumps({'services': services, 'networks': {'shared': {'external': True, 'name': NETWORK}}}))
    call(*compose, 'up', '-d', '--wait', '--wait-timeout', '120')
    print('Real isolated proof APIs ready: Identity 18101, Pricing 18104, Communications 18108. No Orders success is fabricated.')


if __name__ == '__main__':
    main()
