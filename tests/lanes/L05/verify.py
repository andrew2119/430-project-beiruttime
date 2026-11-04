"""Restricted disposable PostgreSQL proofs; reuse local images and bind current source read-only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
os.chdir(ROOT)
parser = argparse.ArgumentParser()
parser.add_argument('--fresh', action='store_true', help='Build test dependencies only when no reusable images exist or dependencies changed')
parser.add_argument('--auction-image')
parser.add_argument('--notices-image')
args = parser.parse_args()
config = json.loads(subprocess.check_output(['./infra/foundation/compose.sh', 'config', '--format', 'json']))
cache = ROOT / 'tests/lanes/L05/artifacts/images.json'
prior = json.loads(cache.read_text()) if cache.exists() else {}
auction_tag = args.auction_image or prior.get('auction')
notice_tag = args.notices_image or prior.get('notices')


def run(*arguments, **kwargs):
    subprocess.run(arguments, check=True, **kwargs)


if args.fresh:
    run_id = hashlib.sha256(str(ROOT).encode()).hexdigest()[:8] + '-' + str(os.getpid())
    auction_tag = 'beirut-time/l05-auction:test-' + run_id
    notice_tag = 'beirut-time/l05-notices:test-' + run_id
    run('docker', 'build', '--target', 'test', '--build-arg', 'SERVICE_PATH=services/auction',
        '-f', 'services/auction/runtime/Dockerfile', '-t', auction_tag, '.')
    run('docker', 'build', '--build-arg', 'AUCTION_TEST_IMAGE=' + auction_tag,
        '-f', 'tests/lanes/L05/communications/Dockerfile', '-t', notice_tag, '.')
if not auction_tag or not notice_tag:
    raise SystemExit('Provide reusable --auction-image and --notices-image, or use --fresh for the initial dependency build.')
for image in (auction_tag, notice_tag):
    run('docker', 'image', 'inspect', image, stdout=subprocess.DEVNULL)
cache.parent.mkdir(parents=True, exist_ok=True)
cache.write_text(json.dumps({'auction': auction_tag, 'notices': notice_tag}) + '\n')
admin_password = config['services']['postgres']['environment']['POSTGRES_PASSWORD']
env = {**os.environ, 'TEST_DATABASE_ADMIN_URL': f'postgresql://postgres:{admin_password}@postgres:5432/postgres',
    'BT_TEST_LANE': 'L05'}
# Finished proof containers remain stopped; shared images, caches, networks and volumes are never pruned here.
container = ['docker', 'run', '--read-only', '--tmpfs', '/tmp', '--cpus', '.5', '--memory', '256m',
    '--label', 'beirut-time.lane=L05', '--network', config['name'] + '_default',
    '-e', 'TEST_DATABASE_ADMIN_URL', '-e', 'BT_SERVICE_NAME', '-e', 'BT_TEST_LANE', '-e', 'TEST_RUNTIME_URL']


def mount(source, target):
    return ['-v', f'{ROOT / source}:{target}:ro']


common = (mount('services/auction/runtime/service_app', '/app/service_app')
    + mount('services/auction/runtime/tests', '/app/tests')
    + mount('services/auction/runtime/conftest.py', '/app/conftest.py')
    + mount('services/auction/runtime/run_tests.py', '/app/run_tests.py')
    + mount('services/auction/runtime/pyproject.toml', '/app/pyproject.toml')
    + mount('tests/lanes/L05', '/lane-tests/L05')
    + mount('packages/contracts-auction/core', '/opt/domain-contracts/bt_contracts/auction/core'))
for package, namespace in [('runtime', 'bt_runtime'), ('events', 'bt_events'),
                           ('bulkheads', 'bt_bulkheads'), ('contracts-core', 'bt_contracts_core')]:
    common += mount(f'packages/{package}/src/{namespace}', f'/opt/venv/lib/python3.11/site-packages/{namespace}')
auction_mounts = common + mount('services/auction/modules', '/app/modules')
notice_mounts = (common + mount('services/communications/modules/bid-notices', '/app/modules/bid-notices')
    + mount('services/auction/modules', '/app/auction-modules'))
run(*container, *auction_mounts, auction_tag, env={**env, 'BT_SERVICE_NAME': 'auction',
    'TEST_RUNTIME_URL': config['services']['auction']['environment']['BT_DATABASE_URL']})
run(*container, *notice_mounts, notice_tag, env={**env, 'BT_SERVICE_NAME': 'communications'})
run(*container, *auction_mounts, auction_tag, 'ruff', 'check', '--no-cache', '/app/service_app', '/app/modules',
    '/lane-tests/L05/auction', '/opt/domain-contracts/bt_contracts/auction/core/models.py',
    env={**env, 'BT_SERVICE_NAME': 'auction'})
run(*container, *notice_mounts, notice_tag, 'ruff', 'check', '--no-cache', '/app/modules', '/lane-tests/L05/communications',
    env={**env, 'BT_SERVICE_NAME': 'communications'})
