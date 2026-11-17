"""Read-only native layouts, version 1. No execution without a checked sandbox.

The installed backend accepts one JSON request on stdin and returns one JSON
response. It must create fresh user, mount, process and private-loopback network
namespaces, enforce resource limits and restricted database roles, and destroy
all per-request state. It must never bind the host root or inherit credentials.
The check operation is diagnostic only; run_service requires separate authority.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

SERVICES = ('identity', 'catalog', 'auction', 'pricing', 'orders', 'eligibility',
            'trust', 'communications', 'service-operations')
BACKEND = Path('/usr/libexec/bt-native-sandbox')
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
        if item.is_symlink() or not (item.is_dir() or item.is_file()):
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
                            timeout=60, env={'PATH': '/usr/bin:/bin'})
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', required=True, action='store_true')
    parser.add_argument('--run-dir', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
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
    except (IsolationError, OSError, ValueError, subprocess.SubprocessError):
        parser.exit(2, 'Native isolation check failed; connected proof deferred.\n')


if __name__ == '__main__':
    main()
