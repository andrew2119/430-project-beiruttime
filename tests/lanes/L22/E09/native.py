"""Local immutable release staging and owned process replacement."""
from dataclasses import dataclass
import compileall
import fcntl
import hashlib
import http.client
from http.cookies import SimpleCookie
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import re
import tarfile
import shutil
import stat
import signal
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlencode, urlsplit
from uuid import UUID

SERVICE_MANIFEST = 'scripts/native-services.json'
ARCHIVE_LIMIT = 1024 ** 3

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


def running(child):
    # Keep the session leader unreaped until all group signals have been sent.
    return os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None


def orders_executable_digest(root, factory, revision, *, archive=None):
    """Hash the tracked Orders application inputs using the same layout for both releases."""
    tracked = subprocess.run(
        ['git', 'ls-tree', '-rz', '--name-only', revision, '--',
         'services/orders/runtime', 'services/orders/modules'],
        cwd=ROOT, capture_output=True, check=True, timeout=30).stdout
    digest = hashlib.sha256(factory.encode() + b'\0')
    count = 0
    runtime = Path('services/orders/runtime')
    for name in filter(None, tracked.split(b'\0')):
        relative = Path(os.fsdecode(name))
        if ('tests' in relative.parts or relative.name.startswith('test_')
                or relative.name == 'conftest.py'
                or (relative.parent == runtime
                    and relative.name in {'run_tests.py', 'package_contracts.py'})
                or (relative.suffix != '.py' and relative.name != 'module.json')):
            continue
        if archive is None:
            path = root / relative
            need(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root),
                 'orders-executable-source')
            stream = path.open('rb')
        else:
            member = archive.getmember('./' + relative.as_posix())
            need(member.isfile(), 'orders-executable-source')
            stream = archive.extractfile(member)
        with stream:
            digest.update(name + b'\0' + hashlib.file_digest(stream, 'sha256').digest())
        count += 1
    need(count > 0, 'orders-executable-source')
    return digest.hexdigest()


def config_digest(environments, root, run):
    stable = {}
    for service, settings in environments.items():
        scope = stable[service] = {}
        for key, value in settings.items():
            if key == 'BT_DATABASE_URL':
                url = urlsplit(value)
                scope[key] = [url.scheme, url.username, url.hostname, url.port, url.path]
            elif key.endswith(('_SECRET', '_TOKEN', '_KEY', '_JWKS', '_PEM', '_PASSWORD')):
                need(bool(value.strip()), service + '-runtime-credential')
                if key.endswith('_PRIVATE_KEY'):
                    from cryptography.hazmat.primitives.serialization import load_pem_private_key
                    try:
                        load_pem_private_key(value.replace('\\n', '\n').encode(), password=None)
                    except (TypeError, ValueError):
                        raise Unavailable(service + '-runtime-signing-key') from None
                if key == 'BT_SIMULATED_PAYMENT_SECRET':
                    need(len(value.encode()) >= 32, 'payment-signing-settings')
                scope[key] = {'runtime_credential': True}
            else:
                scope[key] = value.replace(str(root) + '/', '{release}/').replace(
                    str(run) + '/', '{run}/')
    return hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()


STORE_PATH = Path('node_modules/.pnpm')
NODE = '/usr/bin/node'
RUNTIME_HEADER = 'beirut-time.runtime-sha256'


@dataclass(frozen=True)
class CandidateRuntime:
    store: Path
    python_dependencies: str
    fingerprint: str
    python: str


def mounted_store(checkout):
    store = checkout / STORE_PATH
    need(store.resolve(strict=True) == store and store.is_dir() and os.statvfs(store).f_flag & os.ST_RDONLY,
         'immutable-release-dependency')
    return store


def runtime_tree_digest(root, *, workspace=None):
    """Hash file contents, executable modes and link topology on read-only mounts."""
    digest = hashlib.sha256()
    need(root.is_dir() and not root.is_symlink() and os.statvfs(root).f_flag & os.ST_RDONLY,
         'immutable-candidate-runtime')
    for directory, directories, files in os.walk(root, onerror=lambda error: need(
            False, 'candidate-runtime-inventory')):
        need(os.statvfs(directory).f_flag & os.ST_RDONLY, 'immutable-candidate-runtime')
        for name in sorted(directories + files):
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                link = os.readlink(path)
                target = path.resolve(strict=True)
                value = ['link', link]
                if workspace is not None:
                    # The store occupies the same relative position inside both releases.
                    relocated = Path(os.path.normpath(path.parent / link))
                    need(not Path(link).is_absolute() and (
                        relocated.is_relative_to(root) and target.is_relative_to(root)
                        or (relocated == target and (target == workspace / 'web'
                            or target.parent == workspace / 'packages'))
                    ), 'relocatable-release-dependency')
                elif not target.is_relative_to(root):
                    need(target.is_file(), 'bounded-candidate-runtime-link')
                    value.append(runtime_file_digest(target))
            elif stat.S_ISREG(mode):
                value = ['file', *runtime_file_digest(path)]
            else:
                need(stat.S_ISDIR(mode), 'candidate-runtime-file-type')
                value = ['directory', stat.S_IMODE(mode)]
            digest.update(json.dumps([path.relative_to(root).as_posix(), value]).encode() + b'\n')
        directories.sort()
    return digest.hexdigest()


def runtime_file_digest(path):
    target = path.resolve(strict=True)
    need(target.is_file() and os.statvfs(path.parent).f_flag & os.ST_RDONLY
         and os.statvfs(target).f_flag & os.ST_RDONLY, 'immutable-candidate-runtime')
    with target.open('rb') as stream:
        return [stat.S_IMODE(target.stat().st_mode), hashlib.file_digest(stream, 'sha256').hexdigest()]


def candidate_runtime(python, checkout):
    """Measure the exact external application runtime used by the candidate."""
    # An isolated probe without site hooks exposes the interpreter's built-in import paths.
    executable = Path(python)
    need(executable.is_absolute() and executable.parent.name == 'bin',
         'candidate-python-runtime')
    python_file = runtime_file_digest(executable)
    venv = executable.parent.parent
    site_config = runtime_file_digest(venv / 'pyvenv.cfg')
    probe = subprocess.run([str(executable), '-I', '-S', '-c',
                            'import sys; print(sys.version_info[:2]); print(*sys.path, sep=chr(10))'],
                           env={}, capture_output=True, text=True, check=True, timeout=10)
    version, *paths = probe.stdout.splitlines()
    match = re.fullmatch(r'\((\d+), (\d+)\)', version)
    need(match and paths and all(Path(path).is_absolute() for path in paths),
         'candidate-python-import-paths')
    dependencies = venv / 'lib' / ('python' + '.'.join(match.groups())) / 'site-packages'
    roots = []
    imports = {}
    for path in map(Path, paths):
        if not path.exists() and path.suffix == '.zip' and not path.is_symlink():
            need(os.statvfs(path.parent).f_flag & os.ST_RDONLY, 'immutable-candidate-runtime')
            imports[str(path)] = None
        elif path.is_dir() and not path.is_symlink():
            if not any(path.is_relative_to(parent) for parent in roots):
                imports[str(path)] = runtime_tree_digest(path)
                roots.append(path)
        else:
            imports[str(path)] = runtime_file_digest(path)
    store = mounted_store(checkout)
    measurements = {
        'python': [str(executable), str(executable.resolve()), python_file, site_config, paths, imports],
        'python_dependencies': [str(dependencies), runtime_tree_digest(dependencies)],
        'node': [str(Path(NODE).resolve()), runtime_file_digest(Path(NODE))],
        'store': runtime_tree_digest(store, workspace=checkout),
    }
    fingerprint = hashlib.sha256(json.dumps(measurements, sort_keys=True).encode()).hexdigest()
    return CandidateRuntime(store, str(dependencies), fingerprint, str(executable))


CANDIDATE_PYTHON_ENTRY = """
import sys
sys.dont_write_bytecode = True
sys.path[:0] = sys.argv[1].split(':')
sys.path.append(sys.argv[2])
module = sys.argv[3]
sys.argv[:] = [module, *sys.argv[4:]]
import runpy
runpy.run_module(module, run_name='__main__', alter_sys=True)
"""


def bind_web_dependencies(checkout, release):
    """Keep workspace resolution inside the exported revision."""
    store = mounted_store(checkout)
    (release / STORE_PATH).mkdir(parents=True)
    projects = [Path('web'), *(path.parent.relative_to(release)
                              for path in sorted(release.glob('packages/*/package.json')))]
    for project in projects:
        installed = checkout / project / 'node_modules'
        destination = release / project / 'node_modules'
        if not installed.is_dir():
            continue
        entries = [entry for entry in installed.iterdir() if not entry.name.startswith('.')]
        for scope in tuple(entries):
            if scope.name.startswith('@') and scope.is_dir() and not scope.is_symlink():
                entries.remove(scope)
                entries.extend(scope.iterdir())
        for entry in entries:
            source = entry.resolve(strict=True)
            link = destination / entry.relative_to(installed)
            link.parent.mkdir(parents=True, exist_ok=True)
            if source.is_relative_to(checkout / 'packages'):
                exported = release / source.relative_to(checkout)
                manifest = exported / 'package.json'
                need(manifest.is_file() and json.loads(manifest.read_text())['name']
                     == entry.relative_to(installed).as_posix(), 'exported-workspace-dependency')
                source = Path(os.path.relpath(exported, link.parent))
            else:
                need(source.is_relative_to(store), 'immutable-release-dependency')
                mounted = release / STORE_PATH / source.relative_to(store)
                source = Path(os.path.relpath(mounted, link.parent))
            link.symlink_to(source, target_is_directory=True)
    next_bin = release / 'web/node_modules/.bin/next'
    need((checkout / 'web/node_modules/next/dist/bin/next').is_file(),
         'installed-web-build-entry')
    next_bin.parent.mkdir()
    next_bin.symlink_to('../next/dist/bin/next')


def retain_archive(image, output):
    """Publish the sealed bytes once per run, with no partial handoff."""
    need(os.fstat(image.fileno()).st_size <= ARCHIVE_LIMIT, 'bounded-release-archive')
    with open(f'/proc/self/fd/{image.fileno()}', 'rb') as source, \
            tempfile.NamedTemporaryFile(dir=output, prefix='.candidate-', delete=False) as target:
        temporary = Path(target.name)
        try:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fchmod(target.fileno(), 0o400)
            try:
                os.link(temporary, output / 'candidate.tar')
            except FileExistsError:
                raise Unavailable('fresh-release-archive-handoff') from None
        finally:
            temporary.unlink()


def seal_image(image):
    image.flush()
    fcntl.fcntl(image.fileno(), fcntl.F_ADD_SEALS, fcntl.F_SEAL_WRITE |
                fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL)
    image.seek(0)


def release_image():
    descriptor = os.memfd_create('e09-release', os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
    return os.fdopen(descriptor, 'w+b')


def seal_release(root, revision=None, runtime_fingerprint=None):
    image = release_image()
    try:
        for link in root.rglob('*'):
            if link.is_symlink():
                need(not Path(os.readlink(link)).is_absolute() and link.resolve().is_relative_to(root),
                     'self-contained-release-links')
        headers = {}
        if revision is not None:
            headers['beirut-time.source-revision'] = revision
        if runtime_fingerprint is not None:
            headers[RUNTIME_HEADER] = runtime_fingerprint
        with tarfile.open(fileobj=image, mode='w', format=tarfile.PAX_FORMAT,
                          pax_headers=headers) as archive:
            archive.add(root, arcname='.')
        seal_image(image)
        return image, hashlib.file_digest(image, 'sha256').hexdigest()
    except BaseException:
        image.close()
        raise


def reuse_release(spec, revision, factory, runtime_fingerprint):
    """Measure and launch from the same sealed bytes, even if the input changes."""
    need(isinstance(spec, dict) and set(spec) == {'schema_version', 'archive', 'sha256'}
         and spec['schema_version'] == 1 and isinstance(spec['archive'], str)
         and isinstance(spec['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', spec['sha256']),
         'repeat-release-input')
    path = Path(spec['archive'])
    need(path.is_absolute() and not path.resolve().is_relative_to(ROOT), 'repeat-release-input')
    image = release_image()
    try:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as source:
            info = os.fstat(source.fileno())
            need(stat.S_ISREG(info.st_mode) and info.st_mode & 0o077 == 0,
                 'private-repeat-release-archive')
            need(0 < info.st_size <= ARCHIVE_LIMIT, 'bounded-release-archive')
            remaining = info.st_size
            while remaining:
                block = source.read(min(remaining, 1024 * 1024))
                need(bool(block), 'repeat-release-archive-size')
                image.write(block)
                remaining -= len(block)
            need(not source.read(1), 'repeat-release-archive-size')
        seal_image(image)
        artifact = hashlib.file_digest(image, 'sha256').hexdigest()
        need(artifact == spec['sha256'], 'repeat-release-archive-hash')
        image.seek(0)
        with tarfile.open(fileobj=image, mode='r:') as archive:
            need(archive.pax_headers.get('beirut-time.source-revision') == revision,
                 'repeat-release-source-revision')
            need(archive.pax_headers.get(RUNTIME_HEADER) == runtime_fingerprint,
                 'repeat-release-runtime-hash')
            executable = orders_executable_digest(None, factory, revision, archive=archive)
        return image, artifact, executable
    except BaseException as error:
        image.close()
        if isinstance(error, (OSError, tarfile.TarError, KeyError)):
            raise Unavailable('repeat-release-archive') from None
        raise


PRIOR_PYTHON_PATHS = """
import sys
root = sys.argv[1]
if (not sys.path or any(not path.startswith(root + '/runtime/')
                        for path in sys.path)
        or sys.base_prefix != root + '/runtime'):
    raise SystemExit('prior Python installation is outside the reviewed release')
sys.dont_write_bytecode = True
sys.path[:0] = sys.argv[2].split(':')
sys.path.append(root + '/runtime/site-packages')
"""

PRIOR_PYTHON_ENTRY = PRIOR_PYTHON_PATHS + """
module = sys.argv[3]
sys.argv[:] = [module, *sys.argv[4:]]
import runpy
runpy.run_module(module, run_name='__main__', alter_sys=True)
"""

PRIOR_FORWARD_ENTRY = PRIOR_PYTHON_PATHS + """
import asyncio
from importlib import import_module
import json

import asyncpg
from fastapi import HTTPException
import uvicorn

factory, host, port, ledger = sys.argv[3:]
module, name = factory.split(':', 1)
app = getattr(import_module(module), name)()
expected = json.loads(ledger)
path = '/health/e09-ready'
if any(getattr(route, 'path', None) == path for route in app.routes):
    raise RuntimeError('Forward readiness route already exists')

async def forward_readiness():
    try:
        async with asyncio.timeout(1.5):
            async with app.state.pool.acquire() as connection:
                rows = await connection.fetch(
                    'SELECT step_id, checksum FROM public.migration_ledger')
        if len(rows) == len(expected) and dict(rows) == expected:
            return {'status': 'ready'}
    except (asyncpg.PostgresError, asyncpg.InterfaceError, AttributeError, OSError, TimeoutError):
        pass
    raise HTTPException(503)

app.add_api_route(path, forward_readiness, methods=['GET'], include_in_schema=False)
uvicorn.run(app, host=host, port=int(port))
"""


MIGRATION_INVENTORY = """
import json
from pathlib import Path
from bt_runtime.app.db import migration_steps

steps = migration_steps(Path(sys.argv[3]))
checksums = {name: checksum for name, checksum, _ in steps}
if not checksums or len(checksums) != len(steps):
    raise SystemExit(1)
print(json.dumps(checksums))
"""

RESTORE_SIGNAL_MASK = """
import os
import signal
import sys

mask = {int(number) for number in sys.argv[1].split(',') if number}
for name in ('SIGPIPE', 'SIGXFZ', 'SIGXFSZ'):
    if hasattr(signal, name):
        signal.signal(getattr(signal, name), signal.SIG_DFL)
signal.pthread_sigmask(signal.SIG_SETMASK, mask)
os.execvpe(sys.argv[2], sys.argv[2:], os.environ)
"""

PAYMENT_RECORDS = ('receipts', 'journal', 'custody', 'outbox')


def verify_payment_records(original, current, references, names):
    for name in names:
        before = [row for row in original[name] if row['operation_id'] in references]
        after = [row for row in current[name] if row['operation_id'] in references]
        need(bool(before) and before == after, 'retained-product-' + name)


class Execution:
    def __init__(self, run, settings):
        self.run = run
        self.settings = json.loads(settings.read_text())
        self.manifest = json.loads((ROOT / SERVICE_MANIFEST).read_text())
        self.services = {s['name']: s for s in self.manifest['services']}
        self.previous = {}
        self.releases = {}
        self.children = {}
        self.product_results = {}
        self.payment_attempts = {}
        self.participants = {}
        self.onboarded_organizations = set()
        self.images = {}
        self.orders_executables = {}
        self.compatible_ledgers = {}
        self.partial_measurements = {}
        self.acknowledged_callback_id = None
        self.acknowledged_baseline_ids = set()

    def command(self, args, cwd, env):
        result = subprocess.run(args, cwd=cwd, env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=600, check=False)
        need(result.returncode == 0, 'local-release-command')

    def application_namespace(self):
        return ['/usr/bin/bwrap', '--die-with-parent', '--unshare-pid',
                '--ro-bind', '/', '/', '--proc', '/proc', '--dev', '/dev',
                '--tmpfs', str(self.run)]

    def environment(self, service, root):
        need(self.settings.get('schema_version') == 1, 'native-settings-version')
        scoped = self.settings.get('services', {}).get(service, {}).get('env')
        need(isinstance(scoped, dict), service + '-runtime-environment')
        need(all(isinstance(k, str) and isinstance(v, str) for k, v in scoped.items()),
             service + '-runtime-environment')
        # Use only the verified service scope, never inherited process settings.
        if service == 'web':
            public = {'BT_PUBLIC_WEB_ORIGINS', 'BT_TRUST_FORWARDED_ORIGIN'}
            public.update(name.upper().replace('-', '_') + '_API_URL'
                          for name in self.services if name != 'web')
            env = {key: value for key, value in scoped.items() if key in public}
            need(env.get('BT_TRUST_FORWARDED_ORIGIN', 'false') in {'true', 'false'},
                 'web-origin-settings')
            env.update(HOSTNAME='127.0.0.1', PORT=str(self.services['web']['port']),
                       NODE_ENV='production')
        else:
            env = {k: v for k, v in scoped.items()
                   if not k.startswith(('PG', 'LD_', 'PYTHON')) and 'PASSWORD' not in k
                   and 'OWNER' not in k and 'MIGRATION' not in k}
        env.update(PATH=str(Path(self.settings.get('python', sys.executable)).parent)
                   + ':/usr/bin:/bin', PYTHONDONTWRITEBYTECODE='1',
                   PYTHONUNBUFFERED='1')
        if service == 'web':
            env['PATH'] = '/usr/bin:/bin'
        else:
            address = urlsplit(env.get('BT_DATABASE_URL', ''))
            need(address.scheme in {'postgres', 'postgresql'} and address.username
                 and address.password and not address.username.endswith('_owner')
                 and address.hostname == '127.0.0.1' and address.port == 54329
                 and not address.query and not address.fragment,
                 service + '-runtime-database')
            env['BT_SERVICE_NAME'] = service
        if root == getattr(self, 'reviewed_prior', (None,))[0]:
            env = {key: value for key, value in env.items()
                   if not key.startswith(('LD_', 'PYTHON'))}
            env['PATH'] = str(root / 'runtime/bin') + ':/usr/bin:/bin'
        env['NEXT_TELEMETRY_DISABLED'] = '1'
        # Provider addresses and storage must remain on the private native stack.
        for key, value in env.items():
            values = value.split(',') if key.endswith('_WEB_ORIGINS') else (value,)
            for entry in values:
                if '://' not in entry and not (service == 'web' and
                        (key.endswith('_API_URL') or key == 'BT_PUBLIC_WEB_ORIGINS')):
                    continue
                address = urlsplit(entry.strip())
                need(address.hostname in {'127.0.0.1', 'localhost', '::1'},
                     'loopback-runtime-settings')
                if service == 'web':
                    need(address.scheme in {'http', 'https'}
                         and address.username is None and address.password is None
                         and address.path in {'', '/'} and not address.query
                         and not address.fragment, 'web-private-settings')
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
        self.isolated()
        revision = request['source_revision']
        target = self.run / 'scenarios/e09/releases/candidate'
        target.mkdir(parents=True, mode=0o700)
        self.candidate_runtime = candidate_runtime(self.settings.get('python', sys.executable), ROOT)
        if 'e09_candidate' in self.settings:
            image, artifact, executable = reuse_release(
                self.settings['e09_candidate'], revision, self.services['orders']['factory'],
                self.candidate_runtime.fingerprint)
            mode = 'reused'
        else:
            image, artifact, executable = self.build_release(target, revision)
            mode = 'built'
        self.images[target] = image
        self.orders_executables[target] = executable
        if mode == 'built':
            shutil.rmtree(target)
            target.mkdir(mode=0o700)
            retain_archive(image, self.run / 'scenarios/e09')
        artifacts = {name: artifact + ':' + name for name in self.services}
        self.releases[artifact] = target
        return {'candidate': artifact, 'artifacts': artifacts, 'archive_mode': mode}

    def build_release(self, target, revision):
        # Export exactly the source revision; dependency links use installed local files.
        archive = subprocess.run(['git', 'archive', revision], cwd=ROOT,
                                 capture_output=True, check=True, timeout=30).stdout
        import io
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(target, filter='data')
        bind_web_dependencies(ROOT, target)
        python = self.settings.get('python', sys.executable)
        self.command([python, 'infra/foundation/package-contracts.py', str(target / 'contracts')],
                     target, {'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1'})
        for service in self.services:
            if service != 'web':
                need(compileall.compile_dir(target / 'services' / service, quiet=2),
                     service + '-production-compile')
        # The package build generates the navigation registry in the fresh archive.
        runtime = self.candidate_runtime
        self.command([*self.application_namespace(), '--bind', str(target), str(target),
                      '--ro-bind', str(runtime.store), str(target / STORE_PATH),
                      '--chdir', str(target / 'web'), '--', 'npm', 'run', 'build'],
                     self.run, self.environment('web', target))
        orders_executable = orders_executable_digest(
            target, self.services['orders']['factory'], revision)
        image, artifact = seal_release(target, revision, runtime.fingerprint)
        return image, artifact, orders_executable

    def migration_inventory(self, service, root, *, prior):
        env = self.environment(service, root)
        if prior:
            python = str(root / 'runtime/bin/python3')
            flags = ['-I', '-S', '-B']
            setup = PRIOR_PYTHON_PATHS
        else:
            python = self.settings.get('python', sys.executable)
            flags = ['-I', '-B']
            setup = "import sys\nsys.path[:0] = sys.argv[2].split(':')\n"
        argv = [*self.application_namespace(), '--chdir', str(root), '--', python,
                *flags, '-c', setup + MIGRATION_INVENTORY, str(root),
                env['PYTHONPATH'], env['BT_MODULES_PATH']]
        result = subprocess.run(argv, cwd=self.run, env={'PATH': env['PATH']},
                                capture_output=True, timeout=30)
        need(result.returncode == 0, service + '-release-migration-inventory')
        return json.loads(result.stdout)

    def verify_compatible_ledger(self, service, env, prior, candidate):
        from restore import measure

        need(all(candidate.get(name) == checksum for name, checksum in prior.items()),
             service + '-incompatible-prior-migrations')
        rows = measure(['-d', env['BT_DATABASE_URL']],
                       'SELECT step_id, checksum FROM public.migration_ledger')
        actual = {row['step_id']: row['checksum'] for row in rows}
        need(len(actual) == len(rows) and actual == candidate,
             service + '-candidate-migration-ledger')

    def ready(self, service):
        item = self.services[service]
        path = '/api/health' if service == 'web' else '/health/ready'
        entry = self.children.get(service, {})
        ledgers = self.compatible_ledgers.get(service)
        prior_root = getattr(self, 'reviewed_prior', (None,))[0]
        compatible_prior = ledgers and entry.get('root') == prior_root
        if compatible_prior and ledgers[0] != ledgers[1]:
            path = '/health/e09-ready'
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
                        break
            except OSError:
                pass
            time.sleep(.1)
        else:
            raise Unavailable(service + '-readiness')
        if compatible_prior:
            self.verify_compatible_ledger(service, entry['env'], *ledgers)

    def isolated(self):
        # A fresh namespace must contain the complete private stack.
        host = self.settings.get('e09_host_network_namespace')
        need(isinstance(host, str) and host.startswith('net:[')
             and os.readlink('/proc/self/ns/net') != host,
             'private-stack-network-namespace')
        for filename, field in (('/proc/net/route', 0), ('/proc/net/ipv6_route', -1)):
            rows = Path(filename).read_text().splitlines()
            if filename.endswith('/route'):
                rows = rows[1:]
            need(all(row.split()[field] == 'lo' for row in rows),
                 'loopback-network-isolation')

    def spawn(self, service, argv, cwd, env, stdin=subprocess.DEVNULL, pass_fds=()):
        # Defer termination until the returned handle is inside the cleanup guard.
        blocked = {signal.SIGTERM, signal.SIGINT, signal.SIGALRM}
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
        child = None
        reader = None
        try:
            # Restore the mask after exec, where Python has a fresh interpreter.
            mask = ','.join(str(number) for number in sorted(previous_mask))
            command = [sys.executable, '-I', '-S', '-c', RESTORE_SIGNAL_MASK, mask, *argv]
            child = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, start_new_session=True, stdin=stdin,
                                     restore_signals=True, pass_fds=pass_fds)
            entry = dict(child=child, start=ticks(child.pid),
                         session=os.getsid(child.pid), reader=None)
            self.children[service] = entry
            need(entry['start'] is not None and entry['session'] == child.pid,
                 'owned-process-identity')
            def drain():
                try:
                    while child.stdout.read(65536):
                        pass
                finally:
                    child.stdout.close()
            reader = threading.Thread(target=drain, daemon=True)
            reader.start()
            entry['reader'] = reader
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            return entry
        except BaseException:
            if child is not None:
                # The handle is unreaped, so its newly created group cannot be reused.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=5)
                if reader is not None and reader.ident is not None:
                    reader.join(timeout=2)
                if child.stdout is not None:
                    child.stdout.close()
                self.children.pop(service, None)
            raise
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

    def python_command(self, root, env, module):
        if root == getattr(self, 'reviewed_prior', (None,))[0]:
            return [str(root / 'runtime/bin/python3'), '-I', '-S', '-c',
                    PRIOR_PYTHON_ENTRY, str(root), env['PYTHONPATH'], module]
        python = self.settings.get('python', sys.executable)
        if root in self.images:
            return [self.candidate_runtime.python, '-I', '-S', '-u', '-c', CANDIDATE_PYTHON_ENTRY,
                    env['PYTHONPATH'], self.candidate_runtime.python_dependencies, module]
        return [python, '-m', module]

    def invocation(self, service, root, artifact, env):
        services = (self.prior_services if root == getattr(self, 'reviewed_prior', (None,))[0]
                    else self.services)
        item = services[service]
        if service == 'web':
            argv = [NODE, 'node_modules/next/dist/bin/next', 'start',
                    '--hostname', '127.0.0.1', '--port', str(item['port'])]
            cwd = root / 'web'
        else:
            argv = [*self.python_command(root, env, 'uvicorn'),
                    item['factory'], '--factory', '--host', '127.0.0.1',
                    '--port', str(item['port'])]
            if root == getattr(self, 'reviewed_prior', (None,))[0]:
                ledgers = self.compatible_ledgers.get(service)
                if ledgers and ledgers[0] != ledgers[1]:
                    argv = [str(root / 'runtime/bin/python3'), '-I', '-S', '-c',
                            PRIOR_FORWARD_ENTRY, str(root), env['PYTHONPATH'],
                            item['factory'], '127.0.0.1', str(item['port']),
                            json.dumps(ledgers[1], sort_keys=True)]
            cwd = root
        image = self.images.get(root)
        if image is not None:
            # Extract only sealed bytes into a fresh mount, then expose it read-only.
            script = ('set -eu\n/usr/bin/tar -xf - -C "$1"\n'
                      'root=$1\ncwd=$2\nstore=$3\nstore_mount=$4\nshift 4\n'
                      'exec /usr/bin/bwrap --die-with-parent --ro-bind / / --ro-bind "$root" "$root" '
                      '--ro-bind "$store" "$store_mount" --chdir "$cwd" -- "$@" </dev/null')
            argv = [*self.application_namespace(), '--tmpfs', str(root),
                    '--chdir', '/', '--', '/bin/sh', '-c', script, 'e09',
                    str(root), str(cwd), str(self.candidate_runtime.store), str(root / STORE_PATH), *argv]
        else:
            need(not root.resolve().is_relative_to(self.run), 'prior-outside-private-run')
            argv = [*self.application_namespace(), '--chdir', str(cwd), '--', *argv]
        return dict(root=root, artifact=artifact, argv=tuple(argv), env=dict(env))

    def launch(self, service, root, artifact, env, *, invocation=None):
        if invocation is None:
            self.isolated()
            invocation = self.invocation(service, root, artifact, env)
        argv, env = invocation['argv'], invocation['env']
        image = self.images.get(root)
        if image is None:
            entry = self.spawn(service, argv, self.run, env)
        else:
            with open(f'/proc/self/fd/{image.fileno()}', 'rb') as stream:
                entry = self.spawn(service, argv, self.run, env, stdin=stream)
        entry.update(invocation)
        child = entry['child']
        try:
            self.ready(service)
            need(running(child), service + '-process-exited')
        except BaseException:
            self.stop(service)
            raise
        return entry

    def stop(self, service):
        entry = self.children.get(service)
        if entry is None:
            return
        child = entry['child']
        need(ticks(child.pid) == entry['start']
             and os.getsid(child.pid) == entry['session'] == child.pid,
             'owned-process-identity')

        def group_alive():
            for path in Path('/proc').glob('[0-9]*/stat'):
                try:
                    fields = path.read_text().rsplit(')', 1)[1].split()
                except (FileNotFoundError, ProcessLookupError):
                    continue
                if (fields[0] not in {'Z', 'X'} and int(fields[2]) == child.pid
                        and int(fields[3]) == entry['session']):
                    return True
            return False

        def send(number):
            try:
                os.killpg(child.pid, number)
            except ProcessLookupError:
                pass

        def exited(timeout):
            until = time.monotonic() + timeout
            while group_alive():
                if time.monotonic() >= until:
                    return False
                time.sleep(.05)
            return True

        if group_alive():
            send(signal.SIGTERM)
            if not exited(10) and group_alive():
                send(signal.SIGKILL)
                need(exited(5), 'owned-group-stop-timeout')
        signals = {signal.SIGTERM, signal.SIGINT, signal.SIGALRM}
        mask = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
        try:
            child.wait(timeout=5)
            del self.children[service]
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, mask)
        entry['reader'].join(timeout=2)

    def close(self):
        errors = []
        for service in reversed(tuple(self.children)):
            try:
                self.stop(service)
            except BaseException as error:
                errors.append(error)
        for image in self.images.values():
            image.close()
        self.images.clear()
        if errors:
            raise errors[0]

    def verify_prior(self, root, prior):
        files = prior['files']
        need(isinstance(files, dict) and bool(files), 'prior-artifact-files')
        inventory = set()
        for path in root.rglob('*'):
            need(not path.is_symlink(), 'prior-artifact-path')
            if not path.is_dir():
                need(path.is_file(), 'prior-artifact-path')
                inventory.add(path.relative_to(root).as_posix())
        need(inventory == set(files), 'complete-prior-artifact')
        digest = hashlib.sha256()
        for name, expected in sorted(files.items()):
            path = root / name
            need(not Path(name).is_absolute() and '..' not in Path(name).parts
                 and path.resolve().is_relative_to(root) and not path.is_symlink()
                 and path.is_file(), 'prior-artifact-path')
            need(os.statvfs(path).f_flag & os.ST_RDONLY, 'immutable-prior-release')
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            need(actual == expected, 'prior-artifact-file-hash')
            digest.update(name.encode() + b'\0' + actual.encode() + b'\n')
        need(digest.hexdigest() == prior['artifact'], 'prior-artifact-hash')
        need(prior['schema_file'] in files
             and files[prior['schema_file']] == prior['schema_hash'], 'prior-schema-hash')

        # The stage supplies a separately reviewed, immutable artifact approval.
        approval = Path(prior.get('provenance_file', '')).resolve()
        need(approval.is_file() and not approval.is_relative_to(root)
             and os.statvfs(approval).f_flag & os.ST_RDONLY, 'reviewed-prior-provenance')
        raw = approval.read_bytes()
        need(hashlib.sha256(raw).hexdigest() == prior.get('provenance_hash'),
             'prior-provenance-hash')
        record = json.loads(raw)
        need(record.get('schema_version') == 1 and record.get('reviewed_by')
             and record.get('compatible') is True
             and all(record.get(key) == prior[key] for key in
                     ('source_revision', 'artifact', 'config_hash', 'schema_hash', 'files')),
             'reviewed-prior-provenance')
        revision = prior['source_revision']
        need(isinstance(revision, str) and len(revision) in (40, 64)
             and all(c in '0123456789abcdef' for c in revision), 'prior-source-revision')
        def git(*args):
            result = subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                                    timeout=30, check=False)
            need(result.returncode == 0, 'prior-source-provenance')
            return result.stdout
        need(git('rev-parse', revision + '^{commit}').decode().strip() == revision,
             'prior-source-revision')
        git('merge-base', '--is-ancestor', revision, 'HEAD')
        executable_roots = ('services/', 'packages/', 'web/', 'contracts/', 'scripts/', 'infra/')
        changed = git('diff', '--name-only', revision, 'HEAD').decode().splitlines()
        need(any(name.startswith(executable_roots) and
                 Path(name).suffix in {'.py', '.js', '.mjs', '.ts', '.tsx', '.json', '.sql'}
                 for name in changed), 'distinct-prior-executable-source')
        # Bind every tracked source byte to the approved commit, not its label.
        entries = git('ls-tree', '-rz', '--full-tree', revision).split(b'\0')
        for entry in filter(None, entries):
            metadata, encoded_name = entry.split(b'\t', 1)
            mode, kind, object_id = metadata.split()
            name = encoded_name.decode()
            need(kind == b'blob' and mode in (b'100644', b'100755'),
                 'prior-source-file-type')
            need(name in files and hashlib.sha256(
                 git('cat-file', 'blob', object_id.decode())).hexdigest() == files[name],
                 'prior-source-content')

    def prior_startup_services(self, root, inventory):
        need(SERVICE_MANIFEST in inventory, 'reviewed-prior-service-manifest')
        raw = (root / SERVICE_MANIFEST).read_bytes()
        need(hashlib.sha256(raw).hexdigest() == inventory[SERVICE_MANIFEST],
             'reviewed-prior-service-manifest')
        manifest = json.loads(raw)
        entries = manifest.get('services')
        need(manifest.get('schema_version') == 1 and isinstance(entries, list)
             and all(isinstance(entry, dict) and isinstance(entry.get('name'), str)
                     for entry in entries), 'prior-startup-services')
        services = {entry['name']: entry for entry in entries}
        need(len(entries) == len(services) and set(services) == set(self.services),
             'prior-startup-services')
        for name, entry in services.items():
            need(type(entry.get('port')) is int and entry['port'] == self.services[name]['port'],
                 name + '-prior-startup-port')
            if name != 'web':
                factory = entry.get('factory')
                need(isinstance(factory, str) and re.fullmatch(
                    r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*', factory),
                    name + '-prior-startup-factory')
        return services

    def start(self):
        self.isolated()
        prior = self.settings.get('e09_prior', {})
        need(prior.get('schema_version') == 1 and prior.get('compatible') is True
             and all(prior.get(key) for key in ('source_revision', 'artifact',
                                               'config_hash', 'schema_hash', 'root', 'files', 'schema_file')),
             'compatible-prior-release-input')
        root = Path(prior['root']).resolve()
        need(root.is_dir() and not root.is_relative_to(ROOT)
             and not root.is_relative_to(self.run)
             and prior['source_revision'] != subprocess.run(
                 ['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                 capture_output=True, text=True).stdout.strip(),
             'distinct-prior-release')
        # Require a read-only mounted artifact, not a writable second export.
        need(os.statvfs(root).f_flag & os.ST_RDONLY, 'immutable-prior-release')
        self.verify_prior(root, prior)
        files = prior['files']
        interpreter = 'runtime/bin/python3'
        need(interpreter in files and os.access(root / interpreter, os.X_OK)
             and any(name.startswith('runtime/site-packages/uvicorn/') for name in files),
             'reviewed-prior-python-runtime')
        self.prior_services = self.prior_startup_services(root, files)
        self.reviewed_prior = root, dict(files)
        environments = {name: self.environment(name, root) for name in self.services}
        config = config_digest(environments, root, self.run)
        need(config == prior['config_hash'], 'prior-config-hash')
        self.orders_executables[root] = orders_executable_digest(
            root, self.prior_services['orders']['factory'], prior['source_revision'])
        try:
            for name in self.services.keys() - {'web'}:
                ledgers = (self.migration_inventory(name, root, prior=True),
                           self.migration_inventory(name, ROOT, prior=False))
                self.verify_compatible_ledger(name, environments[name], *ledgers)
                self.compatible_ledgers[name] = ledgers
            for name in self.services:
                self.launch(name, root, prior['artifact'] + ':' + name, environments[name])
        except BaseException:
            self.close()
            raise

    def replace(self, service, root, artifact, *, invocation=None):
        env = self.environment(service, root) if invocation is None else invocation['env']
        with (self.run / 'control.lock').open('a') as control:
            try:
                fcntl.flock(control, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Unavailable('native-supervisor-control-busy') from None
            try:
                before = self.children.get(service)
                need(before is not None, 'native-supervisor-ownership-transfer')
                need(running(before['child']), 'owned-process-exited')
                self.isolated()
                release, separator, name = artifact.rpartition(':')
                reviewed = self.settings.get('e09_prior', {})
                prior_root = getattr(self, 'reviewed_prior', (None,))[0]
                need(separator and release and name == service and (
                    (self.releases.get(release) == root and root in self.images
                     and not self.images[root].closed)
                    or (prior_root == root and reviewed.get('artifact') == release)
                ), 'replacement-release-artifact')
                if invocation is None:
                    invocation = self.invocation(service, root, artifact, env)
                else:
                    need(invocation['root'] == root and invocation['artifact'] == artifact
                         and bool(invocation['argv']), 'replacement-release-invocation')
                executable = {}
                if service == 'orders':
                    executable = dict(before_orders_executable=self.orders_executables[before['root']],
                                      orders_executable=self.orders_executables[root])
                self.stop(service)
                try:
                    after = self.launch(service, root, artifact, env, invocation=invocation)
                except Exception:
                    saved = {key: before[key] for key in ('root', 'artifact', 'argv', 'env')}
                    self.launch(service, saved['root'], saved['artifact'], saved['env'],
                                invocation=saved)
                    raise
                self.previous.setdefault(service, before)
                return dict(service=service, before_pid=before['child'].pid,
                            after_pid=after['child'].pid, before_start=before['start'],
                            after_start=after['start'], before_artifact=before['artifact'],
                            artifact=artifact, ready=True, **executable)
            finally:
                fcntl.flock(control, fcntl.LOCK_UN)

    def resolve_product(self, value):
        if isinstance(value, dict):
            if set(value) == {'$result'}:
                parts = value['$result'].split('/')
                result = self.product_results[parts[0]]
                for part in parts[1:]:
                    result = result[int(part)] if isinstance(result, list) else result[part]
                return result
            return {key: self.resolve_product(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve_product(item) for item in value]
        return value

    def product_headers(self, headers, *, refresh=False):
        result = self.resolve_product(headers)
        auth = headers.get('Authorization')
        if isinstance(auth, dict) and set(auth) == {'$bearer'}:
            name = auth['$bearer']
            need(name in self.participants, 'registered-participant')
            if refresh:
                self.refresh_participant(name)
            result['Authorization'] = 'Bearer ' + self.participants[name][1]
        return {key: str(value) if type(value) is int else value
                for key, value in result.items()}

    def remember_session(self, name, result, response, origin):
        account, token = result['account']['id'], result['access_token']
        cookies = SimpleCookie(response.getheader('Set-Cookie', ''))
        refresh = cookies.get('bt_refresh')
        need(all(isinstance(v, str) and v.strip() for v in (account, token, origin))
             and refresh is not None and 32 <= len(refresh.value) <= 200,
             'registration-session')
        self.participants[name] = (account, token, refresh.value, origin)

    def refresh_participant(self, name):
        account, _, refresh, origin = self.participants[name]
        connection = http.client.HTTPConnection(
            '127.0.0.1', self.services['identity']['port'], timeout=10)
        try:
            connection.request('POST', '/v1/accounts/refresh',
                               headers={'Origin': origin, 'Cookie': 'bt_refresh=' + refresh})
            response = connection.getresponse()
            need(response.status == 200, 'authority-session-refresh')
            raw = response.read(1048577)
            need(len(raw) <= 1048576, 'bounded-authority-session')
            result = json.loads(raw)
            need(result['account']['id'] == account, 'authority-session-identity')
            self.remember_session(name, result, response, origin)
        finally:
            connection.close()

    def bootstrap_operator(self, participant, reason):
        need(isinstance(participant, str) and participant in self.participants,
             'first-operator-registration')
        need(isinstance(reason, str) and 10 <= len(reason.strip()) <= 500
             and '\0' not in reason, 'first-operator-reason')
        entry = self.children.get('identity')
        need(entry and running(entry['child']), 'owned-first-operator-runtime')
        account = self.product_results[participant]['account']
        try:
            result = subprocess.run(
                [*self.application_namespace(), '--chdir', str(entry['root']), '--',
                 *self.python_command(entry['root'], entry['env'], 'service_app.bootstrap_operator'),
                 '--email=' + account['email'], '--reason=' + reason],
                cwd=self.run, env=entry['env'], capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            raise Unavailable('first-operator-command-timeout') from None
        receipt = 'First platform operator granted: ' + account['id'] + '.'
        need(result.returncode == 0 and result.stdout.startswith(receipt.encode()),
             'first-operator-command')
        self.refresh_participant(participant)

    def organization_query(self, service, reference):
        need(service in {'catalog', 'orders'} and isinstance(reference, dict)
             and set(reference) == {'$result'}, 'product-organization-reference')
        value = self.resolve_product(reference)
        try:
            canonical = str(UUID(value)) if isinstance(value, str) else None
        except ValueError:
            canonical = None
        need(canonical and canonical == value and value in self.onboarded_organizations,
             'product-onboarded-organization')
        return '?' + urlencode({'organization_id': value})

    def wait_for_payable_order(self, step):
        path = ''.join(str(self.resolve_product(part)) for part in step['path'])
        match = re.fullmatch(r'/v1/orders/([0-9a-f-]{36})/checkout', path)
        need(match is not None, 'payable-order-path')
        auth = step['headers'].get('Authorization')
        need(isinstance(auth, dict) and set(auth) == {'$bearer'}
             and sum(key.lower() == 'authorization' for key in step['headers']) == 1,
             'payable-order-buyer')
        headers = self.product_headers(step['headers'])
        deadline = time.monotonic() + 30
        while (remaining := deadline - time.monotonic()) > 0:
            connection = http.client.HTTPConnection(
                '127.0.0.1', self.services['orders']['port'], timeout=min(remaining, 5))
            try:
                connection.request('GET', path, headers=headers)
                response = connection.getresponse()
                need(response.status == 200, 'payable-order-read')
                raw = response.read(1048577)
                need(len(raw) <= 1048576, 'bounded-payable-order')
                checkout = json.loads(raw)
            finally:
                connection.close()
            order = checkout['order']
            need(order['id'] == match[1], 'payable-order-identity')
            if checkout.get('payable') is True and order['state'] == 'awaiting_payment':
                need(type(order['revision']) is int and order['revision'] > 0,
                     'payable-order-revision')
                return checkout
            need(order['state'] in {'awaiting_notification', 'awaiting_payment'},
                 'payable-order-state')
            time.sleep(.1)
        raise Unavailable('payable-order-timeout')

    def read_contact_code(self, challenge, participant):
        account = self.participants.get(participant)
        need(account is not None, 'contact-simulator-participant')
        need(isinstance(challenge, dict) and challenge.get('state') == 'pending'
             and challenge.get('delivery_mode') == 'sample_simulator',
             'contact-simulator-challenge')
        try:
            challenge_id = str(UUID(str(challenge.get('id'))))
        except ValueError:
            raise Unavailable('contact-simulator-challenge') from None
        path = '/v1/contacts/challenges/' + challenge_id
        connection = http.client.HTTPConnection(
            '127.0.0.1', self.services['identity']['port'], timeout=10)
        try:
            connection.request('GET', path + '/sample-code',
                               headers={'Authorization': 'Bearer ' + account[1]})
            response = connection.getresponse()
            need(response.status == 200, 'contact-simulator-read')
            raw = response.read(4097)
            need(len(raw) <= 4096, 'bounded-contact-simulator-result')
            result = json.loads(raw)
            need(isinstance(result, dict) and result.get('sample') is True
                 and isinstance(result.get('code'), str)
                 and re.fullmatch(r'[0-9]{6}', result['code']), 'contact-simulator-result')
            return path + '/verify', participant, result['code']
        finally:
            connection.close()

    def prepare_products(self, journey='e09_journey'):
        steps = self.settings.get(journey)
        need(isinstance(steps, list) and 0 < len(steps) <= 128,
             'product-journey-input')
        contact_codes = {}
        for step in steps:
            name = step['id']
            need(isinstance(name, str) and name not in self.product_results,
                 'unique-product-step')
            need('assign_payment_recovery' not in step, 'orders-payment-recovery-assignment-command')
            if 'wait_for_payable' in step:
                need(journey == 'e09_journey' and set(step) == {'id', 'wait_for_payable', 'path', 'headers'}
                     and step['wait_for_payable'] is True, 'payable-order-step')
                self.product_results[name] = self.wait_for_payable_order(step)
                continue
            if 'first_operator' in step:
                need(journey == 'e09_journey' and set(step) == {'id', 'first_operator', 'reason'},
                     'first-operator-step')
                self.bootstrap_operator(step['first_operator'], step['reason'])
                self.product_results[name] = {}
                continue
            if 'contact_challenge' in step:
                need(journey == 'e09_journey' and set(step) == {'id', 'contact_challenge', 'participant'}
                     and isinstance(step['participant'], str)
                     and isinstance(step['contact_challenge'], dict)
                     and set(step['contact_challenge']) == {'$result'}, 'contact-simulator-step')
                contact_codes[name] = self.read_contact_code(
                    self.resolve_product(step['contact_challenge']), step['participant'])
                self.product_results[name] = {}
                continue
            service = step['service']
            need(service in self.services and service != 'web', 'product-service')
            path = ''.join(str(self.resolve_product(part)) for part in step['path'])
            need(path.startswith('/v1/') and '?' not in path and '#' not in path,
                 'product-command-path')
            scoped_headers = step.get('headers', {})
            refresh = journey == 'e09_watermark_journey'
            if refresh and any(key.lower() == 'authorization' for key in scoped_headers):
                auth = scoped_headers.get('Authorization')
                need(isinstance(auth, dict) and set(auth) == {'$bearer'}
                     and sum(key.lower() == 'authorization' for key in scoped_headers) == 1,
                     'watermark-registered-participant')
            headers = {key: value for key, value in
                       self.product_headers(scoped_headers, refresh=refresh).items()
                       if key.lower() not in {'content-type', 'content-length', 'transfer-encoding'}}
            if 'photo_file' in step:
                need(service == 'catalog' and 'body' not in step and re.fullmatch(
                    r'/v1/seller/listings/[0-9a-fA-F-]{36}/media', path), 'catalog-photo-command')
                relative = Path(step['photo_file'])
                photo = self.run / relative
                need(not relative.is_absolute() and '..' not in relative.parts
                     and photo.resolve().is_relative_to(self.run.resolve())
                     and not photo.is_symlink() and photo.is_file(), 'catalog-photo-file')
                with photo.open('rb') as stream:
                    payload = stream.read(8_000_001)
                need(0 < len(payload) <= 8_000_000, 'bounded-catalog-photo')
                headers = {key: value for key, value in headers.items()
                           if key.lower() not in {'x-media-kind', 'x-public-safe', 'x-demo-asset'}}
                headers.update({'Content-Type': 'application/octet-stream',
                                'X-Media-Kind': 'public_photo', 'X-Public-Safe': 'true'})
            else:
                body = self.resolve_product(step['body'])
                code = body.get('code') if isinstance(body, dict) else None
                if isinstance(code, dict) and set(code) == {'$contact_code'}:
                    reference = code['$contact_code']
                    need(isinstance(reference, str) and reference in contact_codes,
                         'contact-simulator-code-reference')
                    verify_path, participant, value = contact_codes[reference]
                    need(service == 'identity' and path == verify_path
                         and step.get('method', 'POST') == 'POST'
                         and scoped_headers.get('Authorization') == {'$bearer': participant}
                         and sum(key.lower() == 'authorization' for key in scoped_headers) == 1,
                         'contact-simulator-verification-scope')
                    body['code'] = value
                    del contact_codes[reference]
                payload = json.dumps(body).encode()
                need(len(payload) <= 65536, 'bounded-product-command')
                headers['Content-Type'] = 'application/json'
            target = path
            if 'organization_id' in step:
                target += self.organization_query(service, step['organization_id'])
            payment = (re.fullmatch(r'/v1/orders/([0-9a-fA-F-]{36})/payment-attempts', path)
                       if service == 'orders' else None)
            method = step.get('method', 'POST')
            need(method == 'POST' or (journey == 'e09_watermark_journey' and method == 'DELETE'),
                 'product-command-method')
            connection = http.client.HTTPConnection(
                '127.0.0.1', self.services[service]['port'], timeout=10)
            try:
                connection.request(method, target, payload, headers)
                response = connection.getresponse()
                if payment and response.status == 503:
                    raw = response.read(1048577)
                    need(len(raw) <= 1048576, 'bounded-product-result')
                    try:
                        error = json.loads(raw)
                    except ValueError:
                        error = {}
                    if isinstance(error, dict) and isinstance(error.get('error'), dict):
                        need(error['error'].get('code') != 'recovery_assignment_unavailable',
                             'orders-payment-recovery-assignment-command')
                need(200 <= response.status < 300, 'product-preparation-accepted')
                raw = response.read(1048577)
                need(len(raw) <= 1048576, 'bounded-product-result')
                result = json.loads(raw)
                # HTTP success can also carry a business denial.
                for pointer, expected in step['expect'].items():
                    actual = result
                    for part in pointer.split('/'):
                        actual = actual[part]
                    need(actual == self.resolve_product(expected), 'product-preparation-outcome')
                need(bool(step['expect']), 'product-preparation-expectation')
                if service == 'identity' and path == '/v1/accounts/register':
                    origin = next((v for k, v in headers.items() if k.lower() == 'origin'), '')
                    self.remember_session(name, result, response, origin)
                if service == 'identity' and path == '/v1/businesses' and (
                        result.get('sample') is False and result.get('state') == 'active'):
                    self.onboarded_organizations.add(result['id'])
                if payment and journey == 'e09_journey' and result.get('status') == 'succeeded':
                    attempt = result.get('attempt', {})
                    if (result.get('paid') is False and attempt.get('state') == 'pending'
                            and attempt.get('order_id') == payment[1]):
                        self.payment_attempts[attempt['id']] = attempt
                self.product_results[name] = result
            finally:
                connection.close()

    def recover_command(self, expected_artifact):
        self.acknowledged_callback_id = None
        binding = self.settings.get('e09_command', {})
        body = self.resolve_product(binding.get('body', {}))
        reference = body.get('event_id')
        need(isinstance(reference, str) and bool(reference), 'product-command-reference')
        need(body.get('outcome') == 'confirmed', 'confirmed-payment-command')
        entry = self.children.get('orders')
        need(entry is not None, 'owned-command-runtime')
        need(entry['artifact'] == expected_artifact, 'recovered-candidate-orders-artifact')
        attempt = self.payment_attempts.get(body.get('attempt_id'))
        need(attempt is not None and all(
            key in body and body[key] == attempt[key]
            for key in ('order_id', 'buyer_id', 'quote_id', 'quote_revision',
                        'currency', 'total_minor', 'route', 'reference')
        ) and body.get('sequence') == attempt['sequence'] + 1,
            'journey-payment-attempt')
        payload = json.dumps(body).encode()
        need(len(payload) <= 65536, 'bounded-product-command')
        headers = {name: value for name, value in
                   self.product_headers(binding.get('headers', {})).items()
                   if name.lower() not in {'content-type', 'content-length',
                                           'transfer-encoding', 'x-bt-signature'}}
        headers['Content-Type'] = 'application/json'
        key = self.settings['services']['orders']['env'].get('BT_SIMULATED_PAYMENT_SECRET', '')
        need(len(key.encode()) >= 32, 'payment-signing-settings')
        headers['X-BT-Signature'] = hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()
        def send(discard):
            connection = http.client.HTTPConnection('127.0.0.1', 8105, timeout=10)
            try:
                connection.request('POST', '/callbacks/v1/simulated', payload, headers)
                if discard:
                    # Keep the request stream open until the database confirms acceptance.
                    until = time.monotonic() + 10
                    while time.monotonic() < until:
                        if self.callback_acknowledged(reference, body['attempt_id'], body['order_id']):
                            self.acknowledged_callback_id = reference
                            return
                        time.sleep(.1)
                    raise Unavailable('durably-acknowledged-product-command')
                response = connection.getresponse()
                need(200 <= response.status < 300, 'product-retry-accepted')
                raw = response.read(1048577)
                need(len(raw) <= 1048576, 'bounded-product-receipt')
                receipt = json.loads(raw)
                attempt = receipt.get('attempt', {})
                need(receipt.get('status') == 'succeeded' and receipt.get('paid') is True
                     and attempt.get('state') == 'confirmed'
                     and attempt.get('id') == body['attempt_id']
                     and attempt.get('order_id') == body['order_id'],
                     'retried-current-held-payment')
            finally:
                connection.close()
        baseline = self.reads()
        need(not any(row['operation_id'] == reference for row in baseline['receipts']),
             'fresh-product-command-reference')
        need(bool(baseline['receipts']) and all(
            row['attempt']['order_id'] != body['order_id'] for row in baseline['receipts']
        ), 'separate-baseline-payment')
        send(True)
        references = {reference}
        observation_error = None
        try:
            original = self.reads()
            self.partial_measurements.update(original)
            before_restart = self.await_payment_inbox(
                original, references, required=False, preserve_payment=True)
        except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
            observation_error = error
        transition = self.replace('orders', entry['root'], entry['artifact'])
        self.partial_measurements.update(transition)
        need(transition['before_artifact'] == transition['artifact'] == expected_artifact,
             'recovered-candidate-orders-artifact')
        send(False)
        if observation_error is not None:
            raise observation_error
        current = self.reads()
        need(all(any(row['operation_id'] == reference for row in snapshot['inbox'])
                 for snapshot in (before_restart, current)),
             'communications-payment-confirmed-delivery')
        from driver import reconcile_snapshot
        need(reference in reconcile_snapshot(current), 'retried-product-receipt')
        verify_payment_records(original, current, references, PAYMENT_RECORDS)
        verify_payment_records(before_restart, current, references, ('inbox',))
        return dict(product_operation_ids=[reference], response_discarded=True,
                    same_reference=True, **current, **transition)

    def authority(self, recovered_order_id):
        probes = self.settings.get('e09_authority', {})
        need(set(probes) == {'allowed', 'denied'}, 'current-authority-probes')
        requests = {}
        identities = set()
        for role, probe in probes.items():
            path = ''.join(str(self.resolve_product(p)) for p in probe['path'])
            match = re.fullmatch(r'/v1/orders/([A-Za-z0-9_-]+)(?:/checkout)?', path)
            need(match is not None, 'authority-probe-path')
            need(match[1] == recovered_order_id, 'authority-recovered-order')
            auth = probe['headers'].get('Authorization')
            need(isinstance(auth, dict) and set(auth) == {'$bearer'}
                 and auth['$bearer'] in self.participants, 'authority-participant')
            need(sum(k.lower() == 'authorization' for k in probe['headers']) == 1,
                 'authority-participant')
            identities.add(self.participants[auth['$bearer']][0])
            requests[role] = (path, auth['$bearer'])
        need(len(identities) == 2 and requests['allowed'][0] == requests['denied'][0],
             'same-order-distinct-participants')
        for role, probe in probes.items():
            path, participant = requests[role]
            self.refresh_participant(participant)
            headers = self.product_headers(probe['headers'])
            connection = http.client.HTTPConnection('127.0.0.1', 8105, timeout=10)
            try:
                connection.request('GET', path, headers=headers)
                response = connection.getresponse()
                need(response.status == (200 if role == 'allowed' else 403),
                     'current-authority-' + role)
                raw = response.read(1048577)
                need(len(raw) <= 1048576, 'bounded-authority-result')
                body = json.loads(raw)
                need(bool(probe['expect']), 'authority-expectation')
                for pointer, expected in probe['expect'].items():
                    actual = body
                    for part in pointer.split('/'):
                        actual = actual[part]
                    need(actual == self.resolve_product(expected), 'authority-outcome')
            finally:
                connection.close()
        return True

    def restore(self, request):
        raise Unavailable('E04-connected-backup-output')

    def owned_database(self, service):
        application = self.children.get(service)
        database = self.children.get('database')
        need(database and running(database['child']) and application and running(application['child']),
             'owned-' + service + '-observations')
        return ['-d', application['env']['BT_DATABASE_URL']]

    def callback_acknowledged(self, reference, attempt, order):
        from observations import confirmed_callback_exists

        return confirmed_callback_exists(self.owned_database('orders'), reference, attempt, order)

    def reads(self):
        from observations import read_orders

        return read_orders(self.owned_database('orders'), self.owned_database('communications'))

    def await_payment_inbox(self, snapshot, references, *, required=True, preserve_payment=False):
        original = snapshot
        deadline = time.monotonic() + 15
        while (not references.issubset(row['operation_id'] for row in snapshot['inbox'])
               and time.monotonic() < deadline):
            time.sleep(.1)
            snapshot = self.reads()
            if preserve_payment:
                verify_payment_records(original, snapshot, references, PAYMENT_RECORDS)
        if required:
            need(references.issubset(row['operation_id'] for row in snapshot['inbox']),
                 'communications-payment-confirmed-delivery')
        return snapshot

    def call(self, action, request):
        if action == 'build':
            result = self.build(request)
        elif action == 'restart':
            name = request['service']
            candidate = request['candidate']
            result = self.replace(name, self.releases[candidate], candidate + ':' + name)
        elif action == 'rollback':
            need('orders' in self.previous, 'native-supervisor-ownership-transfer')
            prior = self.previous['orders']
            candidate = request['candidate']
            current = self.children.get('orders')
            need(current and current['root'] == self.releases.get(candidate)
                 and current['artifact'] == candidate + ':orders',
                 'candidate-orders-rollback')
            need(prior['artifact'] != current['artifact'], 'distinct-prior-release')
            artifact = prior['artifact']
            saved = {key: prior[key] for key in ('root', 'artifact', 'argv', 'env')}
            result = self.replace('orders', prior['root'], artifact, invocation=saved)
            self.partial_measurements.update(result)
            snapshot = self.reads()
            recovered = [row for row in snapshot['receipts']
                         if row['operation_id'] == self.acknowledged_callback_id]
            need(len(recovered) == 1, 'authority-recovered-order')
            order_id = recovered[0]['attempt']['order_id']
            result.update(previous_artifact=artifact, migrations_reversed=False,
                          current_authority_verified=self.authority(order_id), **snapshot)
        elif action == 'restore':
            result = self.restore(request)
        elif action == 'recover-command':
            result = self.recover_command(request['expected_artifact'])
        elif action == 'authoritative-reads':
            result = self.reads()
            if 'candidate' not in request:
                self.partial_measurements.update(result)
                references = {row['operation_id'] for row in result['receipts']}
                result = self.await_payment_inbox(result, references, preserve_payment=True)
        else:
            raise Unavailable('unsupported-native-action')
        return {**request, **result, 'source': 'native', 'synthetic': False,
                'seeded': False, 'state': 'passed'}
