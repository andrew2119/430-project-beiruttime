"""Collect and run one service's full pytest profile against its own PostgreSQL, then report.

Usage: python .github/ci/services.py <service> <report.json>

The collect and run phases each start in a fresh interpreter with a cleared environment.
The run passes only when both phases exit 0, they see the same tests, every test passes
its setup, call and teardown, nothing is skipped, deselected or expected to fail, and every
test the source declares statically was collected.
A service with a manifest (manifests/<service>.txt, one test id per line) also passes only when
it collected and passed every id listed there, each with its setup, call and teardown passed,
and collected no other id from the files the manifest names.
"""
import ast
from collections import defaultdict
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = str(Path(__file__).resolve().parent)
sys.path.insert(0, HERE)
from bt_ci import NAMES, ROOT, SHARED, common_environment, database_urls, ids_digest, package_contracts, \
    work_dir, write_report  # noqa: E402

# These five services carry a migration test that reads the image-only /app/modules path,
# so it runs in the image stage and is left out of the native profile here.
IMAGE_ONLY = {'identity', 'catalog', 'auction', 'eligibility', 'service-operations'}
MANIFESTS = Path(HERE) / 'manifests'


def selection(service):
    runtime = ROOT / 'services' / service / 'runtime'
    roots = (runtime / 'tests', runtime.parent / 'modules', ROOT / 'tests/foundation', ROOT / 'tests/lanes/L00')
    excluded = runtime / 'tests/test_module_migrations.py' if service in IMAGE_ONLY else None
    return runtime, roots, excluded


def environment(service, work, contracts):
    runtime = ROOT / 'services' / service / 'runtime'
    database, owner = database_urls(service)
    venv_bin = Path(sys.executable).parent
    env = common_environment()
    env.update(
        PATH=f'{venv_bin}:/usr/lib/postgresql/17/bin:/usr/bin:/bin', HOME=str(work), TMPDIR=str(work),
        PYTHONPATH=':'.join(map(str, [runtime, runtime.parent, contracts, *SHARED])),
        PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', TEST_RUNTIME_URL=database, BT_DATABASE_URL=database, OWNER_URL=owner,
        BT_SERVICE_NAME=service, BT_MODULES_PATH=str(runtime.parent / 'modules'))
    for name in ('PYTHONUNBUFFERED', 'NEXT_TELEMETRY_DISABLED', 'NODE_OPTIONS', 'UV_THREADPOOL_SIZE',
                 'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        env.pop(name, None)
    return env


def definitions(service):
    """Every test the source declares statically: the floor the collection must cover."""
    _, roots, excluded = selection(service)
    found = set()
    methods = (ast.FunctionDef, ast.AsyncFunctionDef)
    for root in roots:
        for path in sorted(root.rglob('*.py')):
            if path == excluded or not (fnmatchcase(path.name, 'test_*.py') or fnmatchcase(path.name, '*_test.py')):
                continue
            file = path.relative_to(ROOT).as_posix()
            tree = ast.parse(path.read_bytes(), filename=file)
            for part in tree.body:
                if isinstance(part, methods) and part.name.startswith('test'):
                    found.add((file, '', part.name))
                elif isinstance(part, ast.ClassDef) and (part.name.startswith('Test') or any(
                        isinstance(b, ast.Attribute) and b.attr == 'TestCase'
                        or isinstance(b, ast.Name) and b.id == 'TestCase' for b in part.bases)):
                    found.update((file, part.name, m.name) for m in part.body
                                 if isinstance(m, methods) and m.name.startswith('test'))
    return found


class Collector:
    def __init__(self):
        self.rows = []
        self.bad_collection = []
        self.deselected = 0
        self.outcomes = defaultdict(list)

    def pytest_collectreport(self, report):
        if not report.passed:
            self.bad_collection.append(report.nodeid or '<session>')

    def pytest_deselected(self, items):
        self.deselected += len(items)

    def pytest_collection_finish(self, session):
        import pytest
        for item in session.items:
            if not isinstance(item, pytest.Function):
                raise ValueError(f'unsupported test item {item.nodeid}')
            name = getattr(item, 'originalname', None) or item.name.partition('[')[0]
            cls = item.cls.__qualname__ if item.cls else ''
            self.rows.append([item.nodeid, item.path.relative_to(ROOT).as_posix(), cls, name])

    def pytest_runtest_logreport(self, report):
        # An expected failure is reported skipped when it fails and passed when it passes; both carry wasxfail,
        # so neither ever counts as a pass.
        outcome = 'xfail-' + report.outcome if hasattr(report, 'wasxfail') else report.outcome
        self.outcomes[report.nodeid].append([report.when, outcome])


def phase(mode, service, work, contracts):
    """Runs in a fresh child interpreter: one pytest session with a cleared environment."""
    env = environment(service, work, Path(contracts))
    os.environ.clear()
    os.environ.update(env)
    sys.path.remove(HERE)
    sys.path[0:0] = env['PYTHONPATH'].split(':')
    import pytest
    runtime, roots, excluded = selection(service)
    options = ['-c', str(runtime / 'pyproject.toml'), '--rootdir=' + str(ROOT), '-o', f'cache_dir={work}/pytest-cache',
               '-p', 'pytest_asyncio.plugin', '--maxfail=50', '-q', '--import-mode=importlib']
    if excluded:
        options.append('--ignore=' + str(excluded))
    if mode == 'collect':
        options.append('--collect-only')
    collector = Collector()
    code = int(pytest.main([*options, *map(str, roots)], plugins=[collector]))
    result = dict(exit=code, rows=collector.rows, outcomes=collector.outcomes,
                  bad_collection=collector.bad_collection, deselected=collector.deselected)
    (Path(work) / f'{mode}.json').write_text(json.dumps(result))
    return code


def passed_all(outcomes, node):
    """Whether this test passed its setup, call and teardown, and every phase it reported."""
    phases = dict(outcomes.get(node, []))
    return phases.get('setup') == phases.get('call') == phases.get('teardown') == 'passed' \
        and all(outcome == 'passed' for _, outcome in outcomes.get(node, []))


def manifest(service):
    """The exact test ids this service must collect and pass, or None when it has no manifest."""
    path = MANIFESTS / f'{service}.txt'
    if not path.is_file():
        return None
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith('#')]


def check_manifest(listed, collected, ran, outcomes):
    """Problems with the manifest's exact membership, and its counts for the report."""
    ids = set(listed)
    problems = [] if ids and len(ids) == len(listed) else ['manifest: empty or lists an id twice']
    absent = sorted(ids - (collected & ran))
    if absent:
        problems.append(f'manifest: {len(absent)} ids not collected and run, first {absent[:3]}')
    failing = sorted(node for node in ids & collected & ran if not passed_all(outcomes, node))
    if failing:
        problems.append(f'manifest: {len(failing)} ids not passed, first {failing[:3]}')
    files = {node.partition('::')[0] for node in ids}
    extra = sorted(node for node in collected | ran if node.partition('::')[0] in files and node not in ids)
    if extra:
        problems.append(f'manifest: {len(extra)} ids from its files not listed, first {extra[:3]}')
    return problems, dict(manifest=len(ids), manifest_passed=len(ids) - len(absent) - len(failing),
                          manifest_sha256=ids_digest(ids))


def main(service, report):
    if service not in NAMES:
        raise SystemExit(f'unknown service {service}')
    work = work_dir(f'service-{service}')
    contracts = package_contracts(service, work)
    runtime, roots, _ = selection(service)
    problems = [f'missing test root {p.relative_to(ROOT)}' for p in roots if not p.is_dir()]
    results = {}
    for mode in ('collect', 'run'):
        (work / f'{mode}.json').unlink(missing_ok=True)
        print(f'::group::{service} {mode}', flush=True)
        code = subprocess.run([sys.executable, '-I', __file__, '--phase', mode, service, str(work), str(contracts)],
                              cwd=runtime, env={}).returncode
        print('::endgroup::', flush=True)
        path = work / f'{mode}.json'
        if not path.is_file():
            problems.append(f'{mode} phase wrote no result (exit {code})')
            continue
        results[mode] = json.loads(path.read_text())
        if results[mode]['exit'] != 0:
            problems.append(f'{mode} phase exited {results[mode]["exit"]}')
        if results[mode]['bad_collection']:
            problems.append(f'{mode} phase collection errors: {results[mode]["bad_collection"][:5]}')
        if results[mode]['deselected']:
            problems.append(f'{mode} phase deselected {results[mode]["deselected"]} tests')
    collected = {row[0] for row in results.get('collect', {}).get('rows', [])}
    ran = {row[0] for row in results.get('run', {}).get('rows', [])}
    if 'collect' in results and 'run' in results and collected != ran:
        problems.append(f'collect and run differ: {sorted(collected ^ ran)[:5]}')
    if not collected:
        problems.append('no tests collected')
    outcomes = results.get('run', {}).get('outcomes', {})
    passed = 0
    for node in sorted(ran):
        if passed_all(outcomes, node):
            passed += 1
        else:
            problems.append(f'not passed: {node} {outcomes.get(node, [])}')
    declared = {(row[1], row[2], row[3]) for row in results.get('collect', {}).get('rows', [])}
    floor = definitions(service)
    missing = sorted(floor - declared)
    if missing:
        problems.append(f'{len(missing)} declared tests not collected, first {missing[:3]}')
    listed, extra = manifest(service), {}
    if listed is not None:
        found, extra = check_manifest(listed, collected, ran, outcomes)
        # First, so the report's first problems are always the manifest's.
        problems[0:0] = found
    ok = not problems and passed == len(ran) == len(collected) > 0
    return write_report(report, service, ok, problems, collected=len(collected), passed=passed, floor=len(floor),
                        ids_sha256=ids_digest(collected), **extra)


if __name__ == '__main__':
    if sys.argv[1] == '--phase':
        sys.exit(phase(*sys.argv[2:6]))
    sys.exit(main(sys.argv[1], sys.argv[2]))
