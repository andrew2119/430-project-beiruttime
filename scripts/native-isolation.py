"""Read-only native layouts, version 1. No execution without a checked sandbox.

The installed backend accepts one JSON request on stdin and returns one JSON
response. It must create fresh user, mount, process and private-loopback network
namespaces, enforce resource limits and restricted database roles, and destroy
all per-request state. It must never bind the host root or inherit credentials.
The check operation is diagnostic only; run_service requires separate authority.
"""
import argparse
import hashlib
import importlib.util
import os
import tempfile
import json
from pathlib import Path
import re
import subprocess

SERVICES = ('identity', 'catalog', 'auction', 'pricing', 'orders', 'eligibility',
            'trust', 'communications', 'service-operations')
BACKEND = Path('/usr/libexec/bt-native-sandbox')
LAUNCHER = Path('/usr/libexec/bt-native-launch')
ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('user_namespace', 'mount_namespace', 'process_namespace',
            'private_loopback', 'restricted_database_roles', 'resource_scope',
            'readonly_root', 'clean_environment', 'no_host_root')
UNSUPPORTED = ['image_build_context', 'image_content']
SHARED_LANES = ('L00', 'L02', 'L04')
L11_SHARED = ('__init__.py', 'conftest.py', 'real_accounts.py',
              'testing_database.py', 'service_operations_helpers.py',
              'service_operations_tests_data.py')


class IsolationError(ValueError):
    """A required input or isolation property is unavailable."""


def safe_input(root, relative):
    """Reject links, special files and local configuration at every depth."""
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise IsolationError('Input must be repository relative')
    if any(parent.is_symlink() for parent in [path, *path.parents]
           if parent != root and parent.is_relative_to(root)):
        raise IsolationError('Linked input ancestor')
    if not path.exists() or path.is_symlink():
        raise IsolationError('Missing or linked input: ' + relative)
    for item in [path, *path.rglob('*')] if path.is_dir() else [path]:
        if (item.is_symlink() or not (item.is_dir() or item.is_file()) or
                item.is_file() and item.stat().st_nlink != 1):
            raise IsolationError('Unsafe input type')
        if (item.name == '.git' or item.name == '.env' or
                item.name.startswith('.env.') and item.name != '.env.example' or
                item.suffix in ('.pem', '.key', '.p12', '.pfx') or item.name == '__pycache__'):
            raise IsolationError('Excluded local input')
    if not path.resolve().is_relative_to(root.resolve()):
        raise IsolationError('Input escapes source root')
    return str(path.resolve())


def layout(root, service, lane='L00', profile='service'):
    """Build a bounded manifest; sibling runtime source is never mapped."""
    root = Path(root)
    if service not in SERVICES or not re.fullmatch(r'L(0[0-9]|1[01])', lane):
        raise IsolationError('Unknown service or lane')
    if profile not in ('service', 'l05-cross-runtime'):
        raise IsolationError('Unknown profile')
    if profile != 'service' and (service, lane) != ('communications', 'L05'):
        raise IsolationError('Cross-runtime profile requires communications L05')
    mounts = []

    def mount(source, target):
        mounts.append({'source': safe_input(root, source), 'target': target,
                       'read_only': True})

    runtime_service = 'auction' if profile == 'l05-cross-runtime' else service
    mount(f'services/{runtime_service}/runtime', '/app')
    mount(f'services/{service}/modules', '/app/modules')
    mount('tests/foundation', '/foundation-tests')
    mount('tests/lanes/L00', '/lane-tests/L00')
    mount('contracts', '/contracts')
    if (service, lane) == ('communications', 'L03'):
        mount('services/communications/modules/seller-workspace', '/workspace-module')
    empty = []
    if lane == 'L10':
        empty.append('/lane-tests/L10')
    elif lane != 'L00':
        relative = f'tests/lanes/{lane}'
        target = f'/lane-tests/{lane}'
        if lane not in SHARED_LANES:
            relative += '/' + service
            target += '/' + service
        mount(relative, target)
    if lane == 'L11':
        for name in L11_SHARED:
            mount('tests/lanes/L11/' + name, '/lane-tests/L11/' + name)
    if profile == 'l05-cross-runtime':
        mount('services/auction/modules', '/app/auction-modules')
        mount('tests/lanes/L05/auction', '/lane-tests/L05/auction')
    return {'schema_version': 1, 'service': service, 'lane': lane,
            'profile': profile, 'mounts': mounts, 'empty_read_only': empty,
            'contracts_target': '/opt/domain-contracts',
            'working_directory': '/app', 'writable_tmp': '/tmp',
            'limits': {'memory_bytes': 268435456, 'cpu_quota': 0.5, 'pids': 128},
            'network': 'private_loopback', 'required_capabilities': list(REQUIRED),
            'unsupported': UNSUPPORTED.copy()}


def installed_backend(request):
    """Only a fixed administrator-owned entry point may provide isolation."""
    if not BACKEND.is_file():
        raise IsolationError('Installed native sandbox contract is missing')
    stat = BACKEND.stat()
    if BACKEND.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o022:
        raise IsolationError('Native sandbox installation is not protected')
    result = subprocess.run([str(BACKEND)], input=json.dumps(request),
                            text=True, capture_output=True, check=True,
                            timeout=60 if request.get('operation') == 'check' else 610, env={'PATH': '/usr/bin:/bin'})
    return json.loads(result.stdout)


def check_backend(backend=installed_backend):
    response = backend({'schema_version': 1, 'operation': 'check'})
    if (response.get('schema_version') != 1 or
            any(response.get('capabilities', {}).get(key) is not True
                for key in REQUIRED) or
            response.get('published_contracts_read_only') is not True):
        raise IsolationError('Required native isolation is unavailable')
    return response


def staging_check(root, manifest, runner=subprocess.run):
    """Check selected native inputs and nested ignore rules, never image bytes."""
    root = Path(root)
    probes = ['tests/native/n08/nested/.env',
              'tests/native/n08/nested/.env.local',
              'tests/native/n08/nested/.env.production']
    for probe in probes + ['tests/native/n08/nested/.env.example']:
        result = runner(['git', 'check-ignore', '--no-index', '-q', probe],
                        cwd=root, capture_output=True, check=False)
        expected = 1 if probe.endswith('.example') else 0
        if result.returncode != expected:
            raise IsolationError('Nested ignore policy failed')
    for mount in manifest['mounts']:
        safe_input(root, str(Path(mount['source']).relative_to(root.resolve())))
    return {'native_staging': 'supported', 'git_ignore': 'supported',
            'secret_exclusion': 'supported', 'unsupported': UNSUPPORTED.copy()}


def run_service(root, service, *, lane='L00', profile='service',
                backend=installed_backend):
    """Separately authorized per-service entry point for native consumers.

    Database credentials are provided inside the backend's private scope, never
    in this manifest. Administrator scopes must enforce memory, CPU, process
    and network restrictions. Host loopback is not an equivalent substitute.
    Published contracts are supplied read-only by the checked installation.
    """
    manifest = layout(root, service, lane, profile)
    check_backend(backend)
    staging_check(root, manifest)
    argv = ['python', '/app/run_tests.py']
    if profile == 'l05-cross-runtime':
        argv = ['python', '-m', 'pytest', '-c', '/app/pyproject.toml',
                '/lane-tests/L05/communications', '-q', '-o',
                'cache_dir=/tmp/pytest-cache']
    result = backend({'schema_version': 1, 'operation': 'run',
                      'manifest': manifest,
                      'argv': argv,
                      'completion_required': {
                          'proof_id': service + ':' + lane + ':' + profile,
                          'no_skips': True},
                      'environment': {'BT_SERVICE_NAME': service,
                                      'BT_TEST_LANE': lane,
                                      'PYTHONDONTWRITEBYTECODE': '1',
                                      'PYTHONPATH': '/opt/domain-contracts:/app' + (
                                          ':/lane-tests/L05/auction'
                                          if profile == 'l05-cross-runtime' else '')}})
    if (result.get('schema_version') != 1 or
            result.get('isolation_enforced') is not True or
            type(result.get('exit_code')) is not int or result['exit_code'] != 0):
        raise IsolationError('Native execution failed or isolation unconfirmed')
    validate_completion(result, service + ':' + lane + ':' + profile)
    return result


def validate_completion(result, proof_id):
    """Require complete collection and named non-passing outcomes."""
    completion = result.get('completion')
    if not isinstance(completion, dict):
        raise IsolationError('Required completion report missing: ' + proof_id)
    counts = ('collected', 'passed', 'skipped', 'failed', 'errors')
    if (completion.get('proof_id') != proof_id or
            completion.get('state') != 'complete' or
            completion.get('deferred') != [] or
            any(type(completion.get(key)) is not int or completion[key] < 0
                for key in counts) or
            completion.get('collected', 0) == 0 or
            completion.get('passed') != completion.get('collected') or
            any(completion.get(key) != 0 for key in ('skipped', 'failed', 'errors'))):
        raise IsolationError('Required proof incomplete: ' + proof_id)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def canonical_plan(root):
    """Load the local planner, never code selected by an input request."""
    spec = importlib.util.spec_from_file_location('native_lanes', ROOT / 'scripts/native-lanes.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.plan(root)


def absolute_directory(value):
    if not isinstance(value, str) or not Path(value).is_absolute() or '..' in Path(value).parts:
        raise IsolationError('Expected absolute directory')
    path = Path(value)
    if any(item.is_symlink() for item in [path, *path.parents]):
        raise IsolationError('Linked directory ancestor')
    return path


def provider_layout(request, root=ROOT, backend=installed_backend):
    """Describe snapshots only; collection and execution remain separate proofs."""
    if not isinstance(request, dict) or type(request.get('schema_version')) is not int:
        raise IsolationError('Invalid layout request')
    root = absolute_directory(str(root))
    service_request = request.get('operation') == 'runtime-layout'
    if service_request:
        if set(request) != {'schema_version', 'operation', 'source_root', 'service', 'lane', 'run_dir'}:
            raise IsolationError('Invalid service request fields')
        if request['schema_version'] != 1:
            raise IsolationError('Invalid request version')
        root = absolute_directory(request['source_root'])
        directory = absolute_directory(request['run_dir'])
        if directory.is_relative_to(root):
            raise IsolationError('Run directory must be outside the repository')
        manifest = layout(root, request['service'], request['lane'])
        mappings = {m['target']: m['source'] for m in manifest['mounts']}
        if request['lane'] == 'L10':
            mappings['/lane-tests/L10'] = safe_input(root, 'tests/lanes/L10')
        sources = ['scripts/native-runtime-tests.py']
        imports = []
        working = '/app'
        fingerprint = digest(request)
        extra = {'empty_read_only': []}
    else:
        canonical = next((item for item in canonical_plan(root)['selections']
                          if item['id'] == request.get('id')), None)
        if canonical is None or canonical != request:
            raise IsolationError('Selection does not match the current canonical plan')
        topology = canonical['topology']
        mappings = {'/app': safe_input(root, topology['runtime']),
                    '/contracts': safe_input(root, 'contracts')}
        modules = topology['module_roots']
        if len(modules) == 1:
            mappings['/app/modules'] = safe_input(root, modules[0])
        else:
            for module in modules:
                mappings['/app/modules/' + Path(module).name] = safe_input(root, module)
        for name in canonical['sources']:
            if name.startswith('tests/foundation'):
                mappings['/foundation-tests'] = safe_input(root, name)
            elif name.startswith('tests/lanes/'):
                mappings['/lane-tests/' + name.removeprefix('tests/lanes/')] = safe_input(root, name)
        for alias, name in topology.get('path_aliases', {}).items():
            mappings[alias] = safe_input(root, name)
        if canonical['lane'] == 'L11':
            for name in L11_SHARED:
                mappings['/lane-tests/L11/' + name] = safe_input(root, 'tests/lanes/L11/' + name)
        sources = [name for name in canonical['sources'] if name != 'packages']
        sources += topology['import_roots']
        sources += ['scripts/native-runtime-tests.py']
        imports = [safe_input(root, name) for name in topology['import_roots']]
        working = str(root)
        fingerprint = canonical['request_fingerprint']
        extra = {'topology': topology, 'empty_read_only': (
            ['/app/modules'] if topology['core_baseline'] == 'empty' else [])}
    for name in sources:
        safe_input(root, name)
    check_backend(backend)
    protected_executable(LAUNCHER)
    return {'schema_version': 1, 'service': request['service'], 'lane': request['lane'],
            'read_only': True, 'request_fingerprint': fingerprint,
            'launcher': [str(LAUNCHER)], 'source_root': str(root), 'mappings': mappings,
            'sources': list(dict.fromkeys(sources)), 'import_roots': imports,
            'working_directory': working, 'artifacts': {'inputs': [], 'outputs': []}, **extra}


def protected_executable(path):
    if not path.is_file():
        raise IsolationError('Installed native sandbox contract is missing')
    status = path.stat()
    if path.is_symlink() or status.st_uid != 0 or status.st_mode & 0o022 or not status.st_mode & 0o111:
        raise IsolationError('Native sandbox installation is not protected')


def write_private(destination, value, root):
    """Publish a fresh JSON destination atomically with private permissions."""
    destination = Path(destination)
    parent = absolute_directory(str(destination.parent))
    if not destination.is_absolute() or destination.is_relative_to(root):
        raise IsolationError('Result must be outside the repository')
    if destination.exists() or destination.is_symlink():
        raise IsolationError('Result already exists')
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    status = parent.stat()
    if status.st_uid != os.getuid() or status.st_mode & 0o077:
        raise IsolationError('Result parent must be private')
    descriptor, temporary = tempfile.mkstemp(dir=parent, prefix='.layout-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    finally:
        os.unlink(temporary)


def provide(request_file, result_file):
    if request_file.stat().st_size > 1048576:
        raise IsolationError('Layout request too large')
    request = json.loads(request_file.read_text())
    envelope = provider_layout(request)
    if request.get('operation') == 'runtime-layout':
        destination = Path(request['run_dir']) / request['service'] / 'layout.json'
        if destination != result_file:
            write_private(destination, envelope, Path(envelope['source_root']))
    write_private(result_file, envelope, Path(envelope['source_root']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--result', type=Path)
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        if args.request or args.result:
            if not args.request or not args.result or args.check or args.run_dir:
                raise IsolationError('Use --request FILE --result FILE')
            provide(args.request, args.result)
            return
        if not args.check or not args.run_dir:
            raise IsolationError('Use --check --run-dir DIR')
        destination = args.run_dir.resolve()
        if destination.is_relative_to(root):
            raise IsolationError('Run directory must be outside the repository')
        check_backend()
        manifests = [layout(root, service) for service in SERVICES]
        for manifest in manifests:
            staging_check(root, manifest)
        destination.mkdir(parents=True, exist_ok=True)
        output = destination / 'native-layout-v1.json'
        with output.open('x') as stream:
            json.dump({'schema_version': 1, 'layouts': manifests,
                       'unsupported': UNSUPPORTED}, stream, indent=2)
    except (IsolationError, OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
        message = ('Installed native sandbox contract is missing; ' if
                   isinstance(error, IsolationError) and 'missing' in str(error) else '')
        parser.exit(2, message + 'Native isolation check failed; connected proof deferred.\n')


if __name__ == '__main__':
    main()
