"""Host-only Chrome proof. Invoke with bt-heavy.sh; stops every owned process."""
import json
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[3]
os.chdir(root)
config=json.loads(subprocess.check_output(['./infra/foundation/compose.sh','config','--format','json']))
postgres=config['services']['postgres']
port=next(p['published'] for p in postgres['ports'] if p['target']==5432)
subprocess.run([sys.executable,'infra/foundation/package-contracts.py','artifacts/l12-contracts'],check=True)
subprocess.run(['node','web/scripts/generate-nav.mjs'],check=True)
paths=['artifacts/l12-contracts','services/auction/runtime',*[f'packages/{name}/src' for name in ['contracts-core','bulkheads','events','runtime']]]
env={**os.environ,'PYTHONPATH':os.pathsep.join(str(root/path) for path in paths),'BT_L12_BROWSER':'1','BT_MODULES_PATH':str(root/'services/auction/modules'),
    'TEST_DATABASE_ADMIN_URL':f"postgresql://postgres:{postgres['environment']['POSTGRES_PASSWORD']}@127.0.0.1:{port}/postgres"}
subprocess.run([sys.executable,'-m','pytest','-p','bt_runtime.testing','-o','asyncio_mode=auto','tests/lanes/L12/test_browser.py','-q'],check=True,env=env)
