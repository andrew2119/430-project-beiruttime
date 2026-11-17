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
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ('identity', 'catalog', 'auction', 'pricing', 'orders', 'eligibility',
            'trust', 'communications', 'service-operations')


def mappings(service, root=ROOT):
    return {'/app': str(root / 'services' / service / 'runtime'),
            '/app/modules': str(root / 'services' / service / 'modules'),
            '/foundation-tests': str(root / 'tests/foundation'),
            '/lane-tests': str(root / 'tests/lanes'),
            '/contracts': str(root / 'contracts')}


def collection(service, lane, root=ROOT):
    paths = ['tests', 'modules', '/foundation-tests', '/lane-tests/L00']
    if lane != 'L00':
        subtree = root / 'tests/lanes' / lane / service
        paths.append('/lane-tests/' + lane + ('/' + service if subtree.is_dir() else ''))
    return paths


def check_layout(service, run_dir, root=ROOT):
    path = run_dir / service / 'layout.json'
    layout = json.loads(path.read_text())
    if (layout.get('schema_version') != 1 or layout.get('service') != service
            or layout.get('read_only') is not True or layout.get('mappings') != mappings(service, root)):
        raise ValueError('Native layout contract mismatch')
    launcher = layout.get('launcher')
    if not isinstance(launcher, list) or not launcher or not all(isinstance(x, str) and x for x in launcher):
        raise ValueError('Native layout launcher is required')
    for source in mappings(service, root).values():
        if not Path(source).is_dir():
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
    for guest, source in mappings(options.service).items():
        if not Path(guest).samefile(source):
            raise ValueError('Native namespace mapping is missing')
    os.chdir('/app')
    sys.path.insert(0, '/app')
    sys.path.insert(1, '/opt/domain-contracts')
    import pytest
    results = RequiredResults()
    code = int(pytest.main(['-c', '/app/pyproject.toml', *collection(options.service, options.lane),
                           '-q', '-o', 'addopts=', '-o', 'cache_dir=/tmp/pytest-cache'], plugins=[results]))
    status = code if code else (2 if not results.collected or results.incomplete else 0)
    output = {'schema_version': 1, 'service': options.service, 'lane': options.lane,
              'collection': collection(options.service, options.lane), 'collected': results.collected,
              'incomplete': results.incomplete, 'exit_code': status,
              'state': 'complete' if status == 0 else 'incomplete'}
    (options.run_dir / options.service / 'result.json').write_text(json.dumps(output, indent=2) + '\n')
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=SERVICES)
    parser.add_argument('--lane', default='L00')
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--require-all', action='store_true', help='All collected proofs are always required')
    parser.add_argument('--check-layout', action='store_true')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if not re.fullmatch(r'L(0[0-9]|1[01])', options.lane):
        parser.error('Lane must be L00 through L11')
    options.run_dir = options.run_dir.resolve()
    try:
        if options.worker:
            database_environment(options.service, os.environ)
            return worker(options)
        layout, launcher = check_layout(options.service, options.run_dir)
        if options.check_layout:
            return 0
        env = database_environment(options.service, os.environ)
        env['BT_TEST_LANE'] = options.lane
        result = options.run_dir / options.service / 'result.json'
        result.unlink(missing_ok=True)
        code = subprocess.run([*launcher, '--layout', str(layout), '--', sys.executable,
                               str(Path(__file__).resolve()), options.service, '--lane', options.lane,
                               '--run-dir', str(options.run_dir), '--require-all', '--worker'], env=env).returncode
        if code:
            return code
        report = json.loads(result.read_text())
        return 0 if (report.get('schema_version') == 1 and report.get('state') == 'complete'
                     and report.get('service') == options.service and report.get('lane') == options.lane
                     and report.get('collected', 0) > 0 and report.get('exit_code') == 0
                     and report.get('incomplete') == []) else 2
    except (OSError, ValueError, KeyError):
        print('Native proof incomplete: required layout, database or result unavailable', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
