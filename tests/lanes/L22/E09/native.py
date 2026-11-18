"""Local immutable release staging and owned process replacement."""
import compileall
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[4]


class Unavailable(ValueError):
    pass


def need(value, reason):
    if not value:
        raise Unavailable(reason)


def ticks(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except FileNotFoundError:
        return None


class Execution:
    def __init__(self, run, settings):
        self.run = run
        self.settings = json.loads(settings.read_text())
        self.manifest = json.loads((ROOT / 'scripts/native-services.json').read_text())
        self.services = {s['name']: s for s in self.manifest['services']}
        self.previous = {}
        self.releases = {}

    def command(self, args, cwd, env):
        result = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=600, check=False)
        need(result.returncode == 0, 'local-release-command')

    def environment(self, service, root):
        specification = importlib.util.spec_from_file_location(
            'native_runtime', ROOT / 'scripts/native-stack.py')
        runtime = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(runtime)
        env = runtime.environment(self.settings, self.run, self.services[service])
        env['NEXT_TELEMETRY_DISABLED'] = '1'
        # Provider addresses and storage must remain on the private native stack.
        for key, value in env.items():
            if isinstance(value, str) and '://' in value:
                address = urlsplit(value)
                need(address.hostname in {'127.0.0.1', 'localhost', '::1'},
                     'loopback-runtime-settings')
                if address.scheme.startswith('postgres'):
                    need(address.port == 54329, 'private-postgres-port')
        if service != 'web':
            need('BT_DATABASE_URL' in env, service + '-database-settings')
            env['BT_MODULES_PATH'] = str(root / 'services' / service / 'modules')
            env['PYTHONPATH'] = os.pathsep.join(str(p) for p in [
                (self.run / 'contracts' if root == ROOT else root / 'contracts'), root / 'services' / service / 'runtime',
                root / 'services' / service, *[root / 'packages' / p / 'src'
                for p in ('runtime', 'bulkheads', 'events', 'contracts-core')]])
        return env

    def build(self, request):
        # Refuse all external routes before running any build subprocess.
        routes = Path('/proc/net/route').read_text().splitlines()[1:]
        need(all(row.split()[0] == 'lo' for row in routes), 'loopback-network-isolation')
        ipv6 = Path('/proc/net/ipv6_route')
        if ipv6.exists():
            need(all(row.split()[-1] == 'lo' for row in ipv6.read_text().splitlines()),
                 'loopback-network-isolation')
        revision = request['source_revision']
        target = self.run / 'scenarios/e09/releases' / request['operation_id']
        target.mkdir(parents=True, mode=0o700)
        # Export exactly the source revision; dependency links use installed local files.
        archive = subprocess.run(['git', 'archive', revision], cwd=ROOT,
                                 capture_output=True, check=True, timeout=30).stdout
        import io
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(target, filter='data')
        for relative in ('node_modules', 'web/node_modules'):
            local = ROOT / relative
            if local.exists():
                (target / relative).symlink_to(local.resolve(), target_is_directory=True)
        python = self.settings.get('python', sys.executable)
        self.command([python, 'infra/foundation/package-contracts.py', str(target / 'contracts')],
                     target, {'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})
        for service in self.services:
            if service != 'web':
                need(compileall.compile_dir(target / 'services' / service, quiet=2),
                     service + '-production-compile')
        # The network namespace must already contain only the local stack. No fetch/install.
        self.command(['node', 'node_modules/next/dist/bin/next', 'build'],
                     target / 'web', self.environment('web', target))
        digest = hashlib.sha256(archive)
        for file in sorted(target.rglob('*')):
            if file.is_file() and not file.is_symlink() and 'node_modules' not in file.parts:
                digest.update(str(file.relative_to(target)).encode())
                digest.update(file.read_bytes())
        artifact = digest.hexdigest()
        artifacts = {name: artifact + ':' + name for name in self.services}
        self.releases[artifact] = target
        return {'candidate': artifact, 'artifacts': artifacts}

    def ready(self, service):
        item = self.services[service]
        path = '/api/health' if service == 'web' else '/health/ready'
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        # Refuse redirects to any other origin.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener.add_handler(NoRedirect())
        until = time.monotonic() + 30
        while time.monotonic() < until:
            try:
                with opener.open(f"http://127.0.0.1:{item['port']}{path}", timeout=1) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(.1)
        raise Unavailable(service + '-readiness')

    def replace(self, service, root, artifact):
        # Construct and validate generated routing, database and provider settings
        # before entering any process transition.
        self.environment(service, root)
        with (self.run / 'control.lock').open('a') as control:
            try:
                fcntl.flock(control, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Unavailable('native-supervisor-control-busy') from None
            try:
                # The current supervisor retains its original process objects.
                # A disk ledger edit cannot transfer their supervised ownership.
                raise Unavailable('native-supervisor-ownership-transfer')
            finally:
                fcntl.flock(control, fcntl.LOCK_UN)

    def reads(self):
        bindings = self.settings.get('e09_reads', {})
        need(set(bindings) == {'receipts', 'journal', 'custody'},
             'acknowledged-operation-current-read-bindings')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        result = {}
        for name, binding in bindings.items():
            address = urlsplit(binding['url'])
            need(address.scheme == 'http' and address.hostname == '127.0.0.1'
                 and address.port == 8105 and not address.username and not address.password,
                 name + '-owning-read-origin')
            request = urllib.request.Request(binding['url'], headers=binding.get('headers', {}))
            with opener.open(request, timeout=10) as response:
                need(response.status == 200, name + '-current-read')
                raw = response.read(8 * 1024 * 1024 + 1)
            need(len(raw) <= 8 * 1024 * 1024, name + '-bounded-read')
            body = json.loads(raw)
            need(body.get('synthetic') is False and body.get('seeded') is False,
                 name + '-operation-provenance')
            rows = body[name]
            need(isinstance(rows, list) and bool(rows), name + '-operation-coverage')
            result[name] = rows
        return result

    def call(self, action, request):
        if action == 'build':
            result = self.build(request)
        elif action == 'restart':
            name = request['service']
            candidate = request['candidate']
            result = self.replace(name, self.releases[candidate], candidate + ':' + name)
        elif action == 'rollback':
            need('orders' in self.previous, 'native-supervisor-ownership-transfer')
            root, command, artifact = self.previous['orders']
            result = self.replace('orders', root, artifact)
            result.update(previous_artifact=artifact, migrations_reversed=False)
        elif action == 'restore':
            raise Unavailable('E04-connected-backup-output')
        elif action == 'authoritative-reads':
            result = self.reads()
        else:
            raise Unavailable('unsupported-native-action')
        return {**request, **result, 'source': 'native', 'synthetic': False,
                'seeded': False, 'state': 'passed'}
