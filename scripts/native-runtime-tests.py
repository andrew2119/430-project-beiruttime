"""Version 1 native collection/layout/result contract.

The layout provider supplies RUN_DIR/SERVICE/layout.json with schema_version=1,
service, read_only=true, mappings (absolute guest path to repository source),
and launcher (an executable argument list). The launcher accepts
--layout FILE -- COMMAND... and creates a private filesystem namespace with
those read-only mappings. No global links or source rewrites are permitted.
Results are written to RUN_DIR/SERVICE/result.json; incomplete returns 2.
Layout checks are read-only and never launch a process. Connected execution
requires the separately supplied layout provider and isolated database setup.
"""
import argparse
import hashlib
import importlib.util
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ('identity', 'catalog', 'auction', 'pricing', 'orders', 'eligibility',
            'trust', 'communications', 'service-operations')


def mappings(service, root=ROOT, lane="L00"):
    result = {'/app': str(root / 'services' / service / 'runtime'),
            '/app/modules': str(root / 'services' / service / 'modules'),
            '/foundation-tests': str(root / 'tests/foundation'),
            '/lane-tests/L00': str(root / 'tests/lanes/L00'),
            '/contracts': str(root / 'contracts')}

    if lane != 'L00':
        guest = '/lane-tests/' + lane
        if lane not in ('L02', 'L04', 'L10'):
            guest += '/' + service
        result[guest] = str(root / guest.lstrip('/').replace('lane-tests/', 'tests/lanes/', 1))
    if lane == 'L11':
        for name in ('__init__.py', 'conftest.py', 'real_accounts.py', 'testing_database.py',
                     'service_operations_helpers.py', 'service_operations_tests_data.py'):
            result['/lane-tests/L11/' + name] = str(root / 'tests/lanes/L11' / name)
    if (service, lane) == ('communications', 'L05'):
        result['/app'] = str(root / 'services/auction/runtime')
        result['/app/auction-modules'] = str(root / 'services/auction/modules')
        result['/lane-tests/L05/auction/test_admission.py'] = str(
            root / 'tests/lanes/L05/auction/test_admission.py')
    return result


def worker_import_roots(service, lane):
    if (service, lane) == ('communications', 'L05'):
        return ['/opt/domain-contracts', '/app', '/lane-tests/L05/auction']
    return ['/app', '/opt/domain-contracts']


def collection(service, lane, root=ROOT):
    paths = ['tests', 'modules', '/foundation-tests', '/lane-tests/L00']
    if lane != 'L00':
        subtree = root / 'tests/lanes' / lane / service
        paths.append('/lane-tests/' + lane + ('/' + service if subtree.is_dir() else ''))
    return paths


def check_layout(service, run_dir, root=ROOT, lane="L00"):
    path = run_dir / service / 'layout.json'
    layout = json.loads(path.read_text())
    request = service_request(service, lane, run_dir, root)
    if (layout.get('schema_version') != 1 or layout.get('service') != service
            or layout.get('lane') != lane or layout.get('source_root') != str(root)
            or layout.get('request_fingerprint') != digest(request)
            or layout.get('read_only') is not True or layout.get('mappings') != mappings(service, root, lane)):
        raise ValueError('Native layout contract mismatch')
    launcher = layout.get('launcher')
    if launcher != [LAUNCHER]:
        raise ValueError('Native layout launcher is required')
    for source in mappings(service, root, lane).values():
        if not Path(source).exists():
            raise ValueError('Required source directory is missing')
    return path, launcher


def database_environment(service, environ):
    admin = environ.get('TEST_DATABASE_ADMIN_URL', '')
    runtime = environ.get('TEST_RUNTIME_URL', '')
    a, r = urlsplit(admin), urlsplit(runtime)
    if (a.scheme not in {'postgres', 'postgresql'} or a.hostname not in {'localhost', '127.0.0.1', 'postgres'}
            or a.path != '/postgres' or not a.username or a.query or a.fragment):
        raise ValueError('Local maintenance database is required')
    if (r.scheme not in {'postgres', 'postgresql'} or r.hostname != a.hostname
            or r.port != a.port or not re.fullmatch(r'/bt_test_[a-f0-9]+', r.path)
            or r.username != r.path[1:] or r.query or r.fragment):
        raise ValueError('Isolated restricted runtime database is required')
    env = dict(environ)
    env.update(BT_SERVICE_NAME=service, BT_MODULES_PATH='/app/modules')
    env.pop('PYTEST_ADDOPTS', None)
    env.pop('PYTEST_PLUGINS', None)
    env.pop('PYTHONPATH', None)
    return env


class RequiredResults:
    def __init__(self):
        self.collected = 0
        self.incomplete = []

    def pytest_collection_finish(self, session):
        self.collected = len(session.items)

    def pytest_deselected(self, items):
        self.incomplete.extend(item.nodeid for item in items)

    def pytest_collectreport(self, report):
        if report.skipped or report.failed:
            self.incomplete.append(report.nodeid)

    def pytest_runtest_logreport(self, report):
        if report.skipped or getattr(report, 'wasxfail', False):
            self.incomplete.append(report.nodeid)


def worker(options):
    if os.environ.get('BT_NATIVE_SANDBOX') != '1':
        raise ValueError('Native namespace is required')
    for guest, source in mappings(options.service, lane=options.lane).items():
        if not Path(guest).samefile(source):
            raise ValueError('Native namespace mapping is missing')
    os.chdir('/app')
    sys.path[:0] = worker_import_roots(options.service, options.lane)
    import pytest
    results = Observation()
    code = int(pytest.main(['-c', '/app/pyproject.toml', *collection(options.service, options.lane),
                           '-q', '-o', 'addopts=', '-o', 'cache_dir=/tmp/pytest-cache'], plugins=[results]))
    status = code if code else (2 if not results.collected or results.incomplete else 0)
    output = {'schema_version': 1, 'service': options.service, 'lane': options.lane,
              'collection': collection(options.service, options.lane), 'collected': results.collected,
              'incomplete': results.incomplete, 'exit_code': status,
              'collected_nodeids': results.inventory,
              'nodes': [{'nodeid': node, 'outcome': value} for node, value in results.outcomes.items()],
              'state': 'complete' if status == 0 else 'incomplete'}
    write_private(options.run_dir / options.service / 'result.json', output)
    return status


LAUNCHER = '/usr/libexec/bt-native-launch'


def clean_environment():
    return {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}


def write_private(path, value):
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.native-')
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)



def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def service_request(service, lane, run_dir, root=ROOT):
    return {'schema_version': 1, 'operation': 'runtime-layout', 'source_root': str(root),
            'service': service, 'lane': lane, 'run_dir': str(run_dir)}

def obtain_layout(options):
    destination = options.run_dir / options.service
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    request = destination / 'layout-request.json'
    write_private(request, service_request(options.service, options.lane, options.run_dir))
    try:
        (destination / 'layout.json').unlink(missing_ok=True)
        code = subprocess.run([sys.executable, str(ROOT / 'scripts/native-isolation.py'),
                               '--request', str(request), '--result', str(destination / 'layout.json')],
                              env=clean_environment(), capture_output=True, timeout=60).returncode
        if code:
            raise ValueError('Required layout provider unavailable')
        path, _ = check_layout(options.service, options.run_dir, lane=options.lane)
        layout = json.loads(path.read_text())
        layout['sources'] = sorted(set(layout.get('sources', []) + ['scripts/native-runtime-tests.py']))
        layout['artifacts'] = {'inputs': [], 'outputs': [str(destination / 'result.json')]}
        write_private(path, layout)
    finally:
        request.unlink(missing_ok=True)


def lane_contract():
    spec = importlib.util.spec_from_file_location('native_lanes', ROOT / 'scripts/native-lanes.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_request(request, in_namespace=False):
    if request.get('schema_version') != 1 or request.get('operation') not in ('collect', 'execute'):
        raise ValueError('Invalid observation request')
    selection = request['selection']
    contract = lane_contract()
    if in_namespace:
        unsigned = {key: value for key, value in selection.items() if key != 'request_fingerprint'}
        if contract.digest(unsigned) != selection['request_fingerprint']:
            raise ValueError('Selection fingerprint differs')
    else:
        canonical = next((item for item in contract.plan()['selections'] if item['id'] == selection['id']), None)
        if canonical != selection:
            raise ValueError('Selection differs from current plan')
    layout = request['layout']
    if (layout.get('schema_version') != 1 or layout.get('read_only') is not True
            or layout.get('source_root') != str(ROOT)
            or layout.get('request_fingerprint') != selection['request_fingerprint']
            or layout.get('service') != selection['service'] or layout.get('lane') != selection['lane']
            or layout.get('launcher') != [LAUNCHER]):
        raise ValueError('Invalid observation layout')
    if request['operation'] == 'execute':
        contract.validate_collection(selection, request['collection'])
        if request['collection_fingerprint'] != contract.digest(request['collection']):
            raise ValueError('Stale precollection')
    return selection


class Observation(RequiredResults):
    def __init__(self):
        super().__init__()
        self.inventory = []
        self.outcomes = {}
        self.skips = []

    def pytest_collection_finish(self, session):
        super().pytest_collection_finish(session)
        self.inventory = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report):
        super().pytest_runtest_logreport(report)
        if report.failed:
            self.outcomes[report.nodeid] = 'failed' if report.when == 'call' else 'errors'
        elif report.skipped or getattr(report, 'wasxfail', False):
            self.outcomes[report.nodeid] = 'skipped'
            self.skips.append({'nodeid': report.nodeid, 'reason': str(report.longrepr), 'required': True})
        elif report.when == 'call':
            self.outcomes.setdefault(report.nodeid, 'passed')


def before_tests(selection):
    from packaging.requirements import Requirement
    evidence = {}
    for name, operation in selection['check_operations'].items():
        detail = {'operation': operation, 'phase': 'before-tests', 'exit_code': 0,
                  'dependency_fingerprint': selection['dependency_fingerprint']}
        if name == 'dependency-pins':
            observed = {}
            for path in operation['requirements']:
                entries = []
                for line in (ROOT / path).read_text().splitlines():
                    text = line.split('#', 1)[0].strip()
                    if not text:
                        continue
                    requirement = Requirement(text)
                    installed = version(requirement.name)
                    if requirement.url or requirement.marker or installed not in requirement.specifier:
                        raise ValueError('Unsatisfied dependency')
                    entries.append({'requirement': text, 'installed_version': installed, 'satisfied': True})
                observed[path] = entries
            detail['requirements'] = observed
        elif name == 'python-lint':
            code = subprocess.run(operation['argv'], cwd=ROOT, env=dict(os.environ),
                                  capture_output=True).returncode
            if code:
                raise ValueError('Required lint failed')
            detail['executed_argv'] = operation['argv']
        else:
            raise ValueError('Unknown before-tests operation')
        evidence[name] = detail
    return evidence


def observe(request):
    selection = validate_request(request, in_namespace=True)
    if os.environ.get('BT_NATIVE_SANDBOX') != '1':
        raise ValueError('Native namespace is required')
    database_environment(selection['service'], os.environ)
    os.chdir(ROOT)
    topology = selection['topology']
    for name in reversed(topology['import_roots']):
        sys.path.insert(0, str(ROOT / name))
    os.environ.update(topology['environment'])
    os.environ.pop('PYTEST_ADDOPTS', None)
    os.environ.pop('PYTEST_PLUGINS', None)
    command = topology['test_command']
    if command[:3] != ['python3', '-m', 'pytest']:
        raise ValueError('Unsupported test command')
    execute = request['operation'] == 'execute'
    checks = before_tests(selection) if execute else {}
    import pytest
    observations = Observation()
    args = command[3:] + ['--rootdir', str(ROOT), '-o', 'addopts=',
                          '-o', 'cache_dir=/tmp/pytest-cache']
    if not execute:
        args.append('--collect-only')
    code = int(pytest.main(args, plugins=[observations]))
    inventory = observations.inventory
    complete = (code == 0 and bool(inventory) and len(set(inventory)) == len(inventory)
                and not observations.incomplete)
    output = {'schema_version': 1, 'operation': request['operation'],
              'request_fingerprint': selection['request_fingerprint'],
              'lifecycle_policy': topology['lifecycle_policy'],
              'collected_nodeids': inventory, 'complete': complete}
    lane_contract().validate_collection(selection, output)
    if execute:
        complete = complete and set(inventory) == set(request['collection']['collected_nodeids'])
        complete = complete and set(observations.outcomes) == set(inventory)
        counts = {name: sum(value == name for value in observations.outcomes.values())
                  for name in ('passed', 'failed', 'errors', 'skipped')}
        counts['collected'] = len(inventory)
        complete = complete and counts['passed'] == len(inventory)
        output.update(nodes=[{'nodeid': node, 'outcome': outcome}
                             for node, outcome in observations.outcomes.items()],
                      counts=counts, skips=observations.skips, check_execution=checks,
                      exit_code=code, complete=complete,
                      collection_fingerprint=request['collection_fingerprint'])
    if not complete:
        raise ValueError('Incomplete pytest observation')
    return output


def validate_observation(request, output):
    selection = request['selection']
    contract = lane_contract()
    contract.validate_collection(selection, output)
    if request['operation'] == 'execute':
        record = {**output, 'selection_id': selection['id'], 'result': 'passed',
                  'source_fingerprint': selection['source_fingerprint'],
                  'dependency_fingerprint': selection['dependency_fingerprint'],
                  'topology': selection['topology'],
                  'checks': {name: 'passed' for name in selection['checks']}}
        if output.get('exit_code') != 0:
            raise ValueError('Unsuccessful observation')
        contract.validate_record(selection, record, request['collection'])


def observation_main(options):
    result = options.result
    if result is None or result.exists() or result.is_symlink():
        print('Native proof incomplete: fresh result destination required', file=sys.stderr)
        return 2
    try:
        request = json.loads(options.request.read_text())
        validate_request(request, in_namespace=options.provider_worker)
        if options.provider_worker:
            output = observe(request)
            validate_observation(request, output)
            write_private(result, output)
            return 0
        layout = request['layout']
        with tempfile.TemporaryDirectory(prefix='native-observation-', dir=result.parent) as directory:
            private = Path(directory)
            retained = private / 'request.json'
            layout_file = private / 'layout.json'
            write_private(retained, request)
            layout = {
                **layout,
                'sources': sorted(set(layout.get('sources', [])
                                      + ['scripts/native-runtime-tests.py', 'scripts/native-lanes.py'])),
                'artifacts': {'inputs': [{'source': str(retained), 'target': str(retained)}],
                              'outputs': [str(result)]}}
            write_private(layout_file, layout)
            code = subprocess.run([LAUNCHER, '--layout', str(layout_file), '--', sys.executable,
                                   str(Path(__file__).resolve()), '--provider-worker',
                                   '--request', str(retained), '--result', str(result)],
                                  env=clean_environment(), capture_output=True, timeout=600).returncode
        if code:
            raise ValueError('Observation launcher failed')
        output = json.loads(result.read_text())
        if (output.get('complete') is not True or output.get('operation') != request['operation']
                or output.get('request_fingerprint') != request['selection']['request_fingerprint']):
            raise ValueError('Invalid observation response')
        validate_observation(request, output)
        os.chmod(result, 0o600)
        return 0
    except subprocess.TimeoutExpired:
        result.unlink(missing_ok=True)
        print('Native proof incomplete: launcher timed out', file=sys.stderr)
        return 124
    except (OSError, ValueError, KeyError, TypeError, AttributeError, PackageNotFoundError):
        if result is not None:
            result.unlink(missing_ok=True)
        print('Native proof incomplete: required layout, database or result unavailable', file=sys.stderr)
        return 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=SERVICES, nargs='?')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--result', type=Path)
    parser.add_argument('--provider-worker', action='store_true')
    parser.add_argument('--lane', default='L00')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--require-all', action='store_true', help='All collected proofs are always required')
    parser.add_argument('--check-layout', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if options.request:
        return observation_main(options)
    if not options.service or not options.run_dir:
        parser.error('Service and run directory are required')
    if not re.fullmatch(r'L(0[0-9]|1[0-9]|2[0-5])', options.lane):
        parser.error('Lane must be L00 through L25')
    options.run_dir = options.run_dir.resolve()
    try:
        if options.worker:
            database_environment(options.service, os.environ)
            return worker(options)
        if not options.check_layout:
            obtain_layout(options)
        layout, launcher = check_layout(options.service, options.run_dir, lane=options.lane)
        if options.check_layout:
            return 0
        env = clean_environment()
        env['BT_TEST_LANE'] = options.lane
        result = options.run_dir / options.service / 'result.json'
        result.unlink(missing_ok=True)
        code = subprocess.run([*launcher, '--layout', str(layout), '--', sys.executable,
                               str(Path(__file__).resolve()), options.service, '--lane', options.lane,
                               '--run-dir', str(options.run_dir), '--require-all', '--worker'], env=env, capture_output=True, timeout=600).returncode
        if code:
            result.unlink(missing_ok=True)
            return code
        report = json.loads(result.read_text())
        return 0 if (report.get('schema_version') == 1 and report.get('state') == 'complete'
                     and report.get('service') == options.service and report.get('lane') == options.lane
                     and report.get('collected', 0) > 0 and report.get('exit_code') == 0
                     and report.get('incomplete') == []
                     and report.get('collection') == collection(options.service, options.lane)) else 2
    except subprocess.TimeoutExpired:
        (options.run_dir / options.service / 'result.json').unlink(missing_ok=True)
        print('Native proof incomplete: launcher timed out', file=sys.stderr)
        return 124
    except (OSError, ValueError, KeyError, TypeError, AttributeError, PackageNotFoundError):
        print('Native proof incomplete: required layout, database or result unavailable', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
