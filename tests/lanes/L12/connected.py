"""Opt-in isolated connected acceptance; run with bt-heavy.sh --build.

Only explicitly labeled sample accounts/listings are created, using real APIs and
Catalog's guarded importer. Reuses existing images, stops its own containers and
drops only bt_runtime.testing-generated databases. No shared database migrations.
"""
import asyncio
from contextlib import AsyncExitStack
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'artifacts/l12-connected'
ORIGIN='http://127.0.0.1:3412'
IMAGES={'identity':'beirut-time/identity:local','catalog':'beirut-time/catalog:l13-current-7ac6a68d',
        'auction':'beirut-time/auction:l12-proof-4692d5dd','pricing':'beirut-time/pricing:test-aa853aba-31767',
        'orders':'beirut-time/orders:l13-current-7ac6a68d','web':'beirut-time/web:l12-proof-4692d5dd'}
IMAGES={name:os.environ.get('BT_L12_'+name.upper()+'_IMAGE',image) for name,image in IMAGES.items()}


def run(*args,env=None):
    result=subprocess.run(args,env=env,capture_output=True,text=True)
    if result.returncode:
        # Configuration and environment contain credentials. Never print either.
        raise RuntimeError(f'{args[0]} command failed: '+result.stderr[-3000:])
    return result.stdout


def keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization as s
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    return (private.private_bytes(s.Encoding.PEM,s.PrivateFormat.PKCS8,s.NoEncryption()).decode(),
            private.public_key().public_bytes(s.Encoding.PEM,s.PublicFormat.SubjectPublicKeyInfo).decode())


def in_docker(url):
    value=urlparse(url)
    return urlunparse(value._replace(netloc=value.netloc.replace(f'127.0.0.1:{value.port}','postgres:5432')))


async def main():
    from bt_runtime.testing import database_access
    os.chdir(ROOT)
    OUT.mkdir(parents=True,exist_ok=True)
    for port in [3412,3413,3414]:
        assert subprocess.run(['lsof','-nP',f'-iTCP:{port}','-sTCP:LISTEN'],capture_output=True).returncode==1,f'Port {port} occupied'
    config=json.loads(run('./infra/foundation/compose.sh','config','--format','json'))
    postgres=config['services']['postgres']
    port=next(p['published'] for p in postgres['ports'] if p['target']==5432)
    os.environ['TEST_DATABASE_ADMIN_URL']=f"postgresql://postgres:{postgres['environment']['POSTGRES_PASSWORD']}@127.0.0.1:{port}/postgres"
    run(sys.executable,'infra/foundation/package-contracts.py','artifacts/l12-contracts')
    for image in IMAGES.values():
        run('docker','image','inspect',image)
    if os.environ.get('BT_L12_REUSE_WEB_IMAGE')!='1':
        # The caller must use the heavy slot's --build mode.
        result=subprocess.run(['docker','build','--target','runtime','-f','web/Dockerfile','-t',IMAGES['web'],'.'])
        assert result.returncode==0,'Web Docker build failed'
    identity_private,identity_public=keypair()
    service_private,service_public=keypair()
    project='bt-s2-l12-live-'+uuid4().hex[:10]
    base={'BT_AUTH_PUBLIC_KEY':identity_public,
          'BT_SERVICE_AUTH_PRIVATE_KEY':service_private,'BT_SERVICE_AUTH_PUBLIC_KEY':service_public,
          'BT_AUTH_ISSUER':'beirut-time-identity','BT_LOCAL_HTTP':'1','BT_ENVIRONMENT':'demo',
          'BT_ALLOWED_WEB_ORIGINS':ORIGIN,'BT_PUBLIC_WEB_ORIGINS':ORIGIN,'BT_WEB_ORIGIN':ORIGIN,
          'PYTHONPATH':'/foundation/runtime:/opt/domain-contracts','BT_MODULES_PATH':'/app/modules'}
    for name in ['identity','catalog','auction','pricing','orders','communications','eligibility','trust','service-operations']:
        target=f'http://{project}-{name}:8000' if name in IMAGES else 'http://127.0.0.1:3499'
        # Published services retain both legacy and foundation naming schemes.
        # Never let a missing override resolve another proof's shared DNS alias.
        for label in {name.upper(),name.upper().replace('-','_')}:
            for prefix in ['', 'BT_']:
                for suffix in ['_URL','_API_URL']:
                    base[prefix+label+suffix]=target
    compose={'services':{},'networks':{'default':{'external':True,'name':config['name']+'_default'}}}
    with tempfile.TemporaryDirectory(prefix='private-',dir=OUT) as private_dir:
        private=Path(private_dir)
        shutil.copytree(ROOT/'demo',private/'demo')
        shutil.copytree(ROOT/'web/public/demo/watches',private/'demo/watches')
        async with AsyncExitStack() as stack:
            for name in ['identity','catalog','auction','pricing','orders']:
                directory=private/name
                directory.mkdir()
                generator=database_access.__wrapped__(SimpleNamespace(param='core-only'),directory)
                access=await anext(generator)
                stack.push_async_callback(generator.aclose)
                env={**base,'BT_SERVICE_NAME':name,'BT_DATABASE_URL':in_docker(access.runtime_url)}
                if name=='identity':env['BT_AUTH_PRIVATE_KEY']=identity_private
                volumes=[f'{ROOT}/packages/runtime/src:/foundation/runtime:ro',
                         f'{ROOT}/artifacts/l12-contracts:/opt/domain-contracts:ro',
                         f'{ROOT}/services/{name}/runtime/service_app:/app/service_app:ro',
                         f'{ROOT}/services/{name}/modules:/app/modules:ro']
                if name=='catalog':
                    volumes += [f'{private}/demo:/app/demo:ro']
                factory='bt_runtime.app.main:create_app' if name in ['catalog','orders'] else 'service_app.main:create_app'
                service={'image':IMAGES[name],'container_name':project+'-'+name,'environment':env,'volumes':volumes,
                    'command':['uvicorn',factory,'--factory','--host','0.0.0.0','--port','8000','--no-access-log'],
                    'mem_limit':'256m','cpus':0.5,'read_only':True,'tmpfs':['/tmp'],
                    'healthcheck':{'test':['CMD','python','-c',"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/ready')"], 'interval':'2s','timeout':'2s','retries':30}}
                if name=='auction':service['ports']=['127.0.0.1:3413:8000']
                compose['services'][name]=service
                migration_env={**os.environ,**env,'BT_DATABASE_URL':in_docker(access.owner_url)}
                args=['docker','run','--name',project+'-migrate-'+name,'--network',config['name']+'_default',
                      '--memory','256m','--cpus','0.5','--read-only','--tmpfs','/tmp']
                for key in env:args+=['-e',key]
                for mount in volumes:args+=['-v',mount]
                args += [IMAGES[name],'python','-c','import asyncio,os; from pathlib import Path; from bt_runtime.app.db import migrate; asyncio.run(migrate(os.environ["BT_DATABASE_URL"],Path("/app/modules")))']
                run(*args,env=migration_env)
            web_env={name.upper()+'_API_URL':f'http://{project}-{name}:8000' for name in ['identity','catalog','auction','pricing','orders']}
            for name in ['ELIGIBILITY','TRUST','COMMUNICATIONS','SERVICE_OPERATIONS']:web_env[name+'_API_URL']='http://127.0.0.1:3499'
            compose['services']['web']={'image':IMAGES['web'],'container_name':project+'-web',
                'environment':{**web_env,'BT_ALLOWED_WEB_ORIGINS':ORIGIN,'BT_PUBLIC_WEB_ORIGINS':ORIGIN},
                'ports':['127.0.0.1:3412:3000'],'mem_limit':'512m','cpus':0.5,
                'healthcheck':{'test':['CMD','node','-e',"fetch('http://127.0.0.1:3000/api/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"], 'interval':'2s','timeout':'2s','retries':30}}
            path=private/'compose.json'
            path.touch(mode=0o600)
            path.write_text(json.dumps(compose))
            cmd=['docker','compose','-f',str(path),'-p',project]
            proof=None
            try:
                run(*cmd,'up','-d','--no-build','--wait','--wait-timeout','100')
                from connected_scenarios import Scenarios
                proof=Scenarios(ORIGIN,OUT,project)
                await asyncio.to_thread(proof.prepare)
                await asyncio.to_thread(proof.policy_cases)
                await asyncio.to_thread(proof.browser)
                await asyncio.to_thread(proof.race)
                await asyncio.to_thread(proof.fixed_deadline_close)
                print('Connected fixed policy, reviewed bid recovery, auction purchase denial and reserve no-sale passed.',flush=True)
            finally:
                try:
                    if proof:proof.save()
                    for name in ['identity','catalog','auction','pricing','orders','web']:
                        result=subprocess.run(['docker','logs',project+'-'+name],capture_output=True,text=True)
                        (OUT/(name+'.log')).write_text(result.stdout+result.stderr)
                finally:
                    try:run(*cmd,'stop','-t','5')
                    finally:subprocess.run(['chrome-devtools-axi','stop'],env={**os.environ,'CHROME_DEVTOOLS_AXI_SESSION':'bt-s2-l12'},capture_output=True)


if __name__=='__main__':
    # Explicit source path, including the contract packager's namespace layout.
    paths=['artifacts/l12-contracts',*[f'packages/{name}/src' for name in ['runtime','contracts-core','bulkheads','events']]]
    sys.path[:0]=[str(ROOT/path) for path in paths]
    asyncio.run(main())
