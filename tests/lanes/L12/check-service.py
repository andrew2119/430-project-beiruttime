"""Run under bt-heavy.sh: one Auction image and isolated restricted test databases."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

root=Path(__file__).resolve().parents[3]
os.chdir(root)
compose=['./infra/foundation/compose.sh']
config=json.loads(subprocess.check_output([*compose,'config','--format','json']))
if 'postgres' not in subprocess.check_output([*compose,'ps','--services','--status','running'],text=True).splitlines():
    raise SystemExit('Shared foundation PostgreSQL must already be running; do not start another stack')
tag='beirut-time/auction:l12-test-'+hashlib.sha256(str(root).encode()).hexdigest()[:8]
if subprocess.run(['docker','image','inspect',tag],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
    raise SystemExit('Build the reusable Auction test image in a bt-heavy.sh --build run first: '+tag)
subprocess.run([sys.executable,'infra/foundation/package-contracts.py','artifacts/l12-contracts'],check=True)
mounts=[]
for source,target in [('services/auction/runtime/service_app','/app/service_app'),('services/auction/modules','/app/modules'),('tests/lanes/L12','/lane-tests/L12'),('artifacts/l12-contracts','/opt/domain-contracts')]:
    mounts.extend(['-v',str(root/source)+':'+target+':ro'])
env={**os.environ,'TEST_DATABASE_ADMIN_URL':f"postgresql://postgres:{config['services']['postgres']['environment']['POSTGRES_PASSWORD']}@postgres:5432/postgres",'BT_SERVICE_NAME':'auction','TEST_RUNTIME_URL':config['services']['auction']['environment']['BT_DATABASE_URL']}
subprocess.run(['docker','run','--name','bt-s2-l12-test-'+uuid4().hex[:10],'--memory','256m','--cpus','0.5','--pids-limit','128','--read-only','--tmpfs','/tmp','--network',config['name']+'_default','-e','TEST_DATABASE_ADMIN_URL','-e','BT_SERVICE_NAME','-e','TEST_RUNTIME_URL',*mounts,tag,'python','-m','pytest','-c','/app/pyproject.toml','tests','modules','/foundation-tests','/lane-tests/L12','-q','-o','cache_dir=/tmp/pytest-cache'],check=True,env=env)
