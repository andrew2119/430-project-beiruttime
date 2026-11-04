"""Isolated module proofs with reusable dependencies and current read-only sources."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4

root=Path(__file__).resolve().parents[3]
os.chdir(root)
integration=os.getenv('BT_L09_INTEGRATION_ONLY','')
if integration not in ('','directory'):
    raise SystemExit('Unknown integration proof')
if integration and not (root/'services/service-operations/modules/directory/module.json').exists():
    raise SystemExit('Copy the published Directory V1 snapshot before its integration proof')
config=json.loads(subprocess.check_output(['./infra/foundation/compose.sh','config','--format','json']))
run_id=hashlib.sha256(str(root).encode()).hexdigest()[:10]+'-'+uuid4().hex[:8]
tag=os.getenv('BT_L09_TEST_IMAGE')
if not tag:
    tag='beirut-time/l09-proof:'+run_id
    subprocess.run(['docker','build','--target','test','-f','services/trust/runtime/Dockerfile','-t',tag,'.'],check=True)
print('Reusable test image: '+tag,flush=True)
env={**os.environ,'TEST_DATABASE_ADMIN_URL':'postgresql://postgres:'+config['services']['postgres']['environment']['POSTGRES_PASSWORD']+'@postgres:5432/postgres','BT_TEST_LANE':'L09'}
artifacts=root/'artifacts'/'l09'
artifacts.mkdir(parents=True,exist_ok=True)
with TemporaryDirectory(prefix='contracts-',dir=artifacts) as contracts:
    os.chmod(contracts,0o755)
    subprocess.run(['python3','infra/foundation/package-contracts.py',contracts],check=True)
    mounts=[]
    for source,destination in (
        (root/'services/trust/runtime/tests','/app/tests'),
        (root/'tests/foundation','/foundation-tests'),
        (root/'tests/lanes','/lane-tests'),
        (root/'packages/runtime/src','/proof/runtime'),
        (root/'packages/events/src','/proof/events'),
        (root/'packages/bulkheads/src','/proof/bulkheads'),
        (root/'packages/contracts-core/src','/proof/core'),
        (Path(contracts),'/opt/domain-contracts'),
    ):
        mounts.extend(['-v',str(source)+':'+destination+':ro'])
    for service in (('service-operations',) if integration else ('trust','communications','service-operations')):
        env['TEST_RUNTIME_URL']=config['services'][service]['environment']['BT_DATABASE_URL']
        # Foreground containers exit stopped; do not remove shared images/cache or storage.
        subprocess.run(['docker','run','--name','bt-l09-proof-'+run_id+'-'+service,
            '--memory','256m','--cpus','0.5','--pids-limit','128','--read-only','--tmpfs','/tmp',
            '--network',config['name']+'_default','-e','TEST_DATABASE_ADMIN_URL','-e','TEST_RUNTIME_URL',
            '-e','BT_TEST_LANE','-e','BT_SERVICE_NAME='+service,
            '-e','PYTHONPATH=/opt/domain-contracts:/proof/runtime:/proof/events:/proof/bulkheads:/proof/core',
            *mounts,'-v',str(root/'services'/service/'modules')+':/app/modules:ro',
            *(['--entrypoint','/opt/venv/bin/python'] if integration else []),tag,
            *(['-m','pytest','-p','bt_runtime.testing','-c','/app/pyproject.toml',
                '/lane-tests/L09/integration/directory.py','-q','-o','cache_dir=/tmp/pytest-cache'] if integration else [])],env=env,check=True)
