"""Test isolated databases/roles without migrating any ordinary domain database."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

os.chdir(Path(__file__).resolve().parents[1])
COMPOSE = ['./infra/foundation/compose.sh']

def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)

def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('container', 'native'), default='container')
    parser.add_argument('--lane', default=os.environ.get('BT_TEST_LANE', 'L00'))
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--require-all', action='store_true')
    parser.add_argument('services', nargs='*')
    options = parser.parse_args(argv)
    services = ['identity','catalog','auction','pricing','orders','eligibility','trust','communications','service-operations']
    selected = options.services or services
    if not set(selected) <= set(services):
        parser.error('Select a domain service')
    if options.backend == 'native':
        if options.run_dir is None:
            parser.error('--run-dir is required for native execution')
        for name in selected:
            env = dict(os.environ)
            run(os.sys.executable, str(Path(__file__).with_name('native-runtime-tests.py')),
                name, '--lane', options.lane, '--run-dir', str(options.run_dir), '--require-all', env=env)
        return
    container(selected)


def container(selected):
    config = json.loads(subprocess.check_output([*COMPOSE,'config','--format','json']))
    services = ['identity','catalog','auction','pricing','orders','eligibility','trust','communications','service-operations']
    selected = selected or services
    if not set(selected) <= set(services):
        raise SystemExit('Select a domain service')
    was_running = 'postgres' in subprocess.check_output([*COMPOSE,'ps','--services','--status','running'], text=True).splitlines()
    if not was_running:
        run(*COMPOSE,'up','-d','--wait','--no-recreate','postgres')
    try:
        admin_password = config['services']['postgres']['environment']['POSTGRES_PASSWORD']
        run_id = hashlib.sha256(str(Path.cwd()).encode()).hexdigest()[:8] + '-' + str(os.getpid())
        for name in selected:
            tag = f'beirut-time/{name}:test-{run_id}'
            build = config['services'][name]['build']
            args = [arg for key, value in build.get('args', {}).items() for arg in ['--build-arg', f'{key}={value}']]
            run('docker','build','--target','test','-f',build['dockerfile'],*args,'-t',tag,'.')
            env = {**os.environ,
                'TEST_DATABASE_ADMIN_URL': f'postgresql://postgres:{admin_password}@postgres:5432/postgres',
                'TEST_RUNTIME_URL': config['services'][name]['environment']['BT_DATABASE_URL'],
                'BT_SERVICE_NAME': name}
            run('docker','run','--rm','--memory','256m','--cpus','0.5','--pids-limit','128',
                '--read-only','--tmpfs','/tmp','--network', f'{config["name"]}_default',
                '-e','TEST_DATABASE_ADMIN_URL','-e','TEST_RUNTIME_URL','-e','BT_SERVICE_NAME','-e','BT_TEST_LANE','-e','BT_MODULES_PATH',tag, env=env)
    finally:
        # Shared storage stays available to other domains; opt-in cleanup is for a lone run only.
        if not was_running and os.environ.get('STOP_TEST_POSTGRES') == '1':
            run(*COMPOSE,'stop','postgres')


if __name__ == '__main__':
    main()
