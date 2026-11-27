"""Run through bt-heavy.sh. Reuse images; bind current owned source read-only."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
IMAGES = {service: os.environ.get('BT_L14_' + service.upper() + '_TEST_IMAGE', f'beirut-time/{service}:l14-test')
          for service in ['pricing', 'auction']}


def main():
    selected = sys.argv[1:] or ['pricing', 'auction']
    if not set(selected) <= IMAGES.keys():
        raise SystemExit('Choose pricing or auction')
    config = json.loads(subprocess.check_output(['./infra/foundation/compose.sh', 'config', '--format', 'json'], cwd=ROOT))
    contracts = ROOT / 'tests/lanes/L14/.local/domain-contracts'
    subprocess.run([sys.executable, 'infra/foundation/package-contracts.py', str(contracts)], cwd=ROOT, check=True)
    for service in selected:
        subprocess.run(['docker', 'image', 'inspect', IMAGES[service]], stdout=subprocess.DEVNULL, check=True)
        env = {**os.environ, 'BT_TEST_LANE': 'L14', 'BT_SERVICE_NAME': service,
            'TEST_DATABASE_ADMIN_URL': 'postgresql://postgres:' + config['services']['postgres']['environment']['POSTGRES_PASSWORD'] + '@postgres:5432/postgres',
            'TEST_RUNTIME_URL': config['services'][service]['environment']['BT_DATABASE_URL']}
        runtime = ROOT / f'services/{service}/runtime'
        mounts = [(runtime / 'service_app', '/app/service_app'), (runtime / 'tests', '/app/tests'),
            (runtime / 'run_tests.py', '/app/run_tests.py'), (runtime / 'conftest.py', '/app/conftest.py'),
            (runtime / 'pyproject.toml', '/app/pyproject.toml'), (ROOT / f'services/{service}/modules', '/app/modules'),
            (contracts, '/opt/domain-contracts'), (ROOT / 'tests/lanes/L14', '/lane-tests/L14'),
            (ROOT / 'tests/foundation', '/foundation-tests')]
        command = ['docker', 'run', '--rm', '--read-only', '--tmpfs', '/tmp', '--memory', '256m', '--cpus', '0.5',
            '--pids-limit', '128', '--network', config['name'] + '_default']
        for source, target in mounts:
            command += ['-v', f'{source}:{target}:ro']
        for name in ['BT_TEST_LANE', 'BT_SERVICE_NAME', 'TEST_DATABASE_ADMIN_URL', 'TEST_RUNTIME_URL']:
            command += ['-e', name]
        subprocess.run([*command, IMAGES[service], 'python', '/app/run_tests.py'], env=env, cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
