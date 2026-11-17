"""Version 1 native selection dispatch. Providers exchange JSON, never shell text.

Offline planning reads only repository sources. Execution requires separately supplied
collection and read-only layout providers. Each is invoked with --request FILE
--result FILE. Layout output must bind the request fingerprint and read_only=true;
collection output follows validate_record below. Missing providers remain failures.
Run directories must be outside the source tree. No runtime admission is granted here.
"""
import argparse
import ast
import hashlib
import json
import os
import signal
from pathlib import Path
import subprocess
import sys

from packaging.requirements import Requirement, InvalidRequirement
from packaging.version import Version, InvalidVersion

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_suffix('.json')
PROVIDER_TIMEOUT_SECONDS = 3600
CLEANUP_TIMEOUT_SECONDS = 5


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def fingerprint(root, paths):
    files = {}
    for name in sorted(set(paths)):
        path = root / name
        if not path.exists():
            files[name] = None
            continue
        for file in sorted(path.rglob('*')) if path.is_dir() else [path]:
            if (file.is_file() and not {'__pycache__', 'node_modules', '.next', '.git'}
                    .intersection(file.parts) and file.suffix != '.pyc'):
                files[file.relative_to(root).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    return digest(files)


def expected_nodes(root, paths):
    """Read test definitions without importing any runtime or suite."""
    nodes = set()
    for name in paths:
        path = root / name
        if not path.exists():
            raise ValueError('Missing required test root: ' + name)
        files = sorted(path.rglob('test_*.py')) if path.is_dir() else [path]
        for file in files:
            if not file.is_file():
                raise ValueError('Invalid required test file: ' + name)
            tree = ast.parse(file.read_text())
            prefix = file.relative_to(root).as_posix()
            for item in tree.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith('test_'):
                    nodes.add(prefix + '::' + item.name)
                if isinstance(item, ast.ClassDef) and item.name.startswith('Test'):
                    for method in item.body:
                        if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith('test_'):
                            nodes.add(prefix + '::' + item.name + '::' + method.name)
    return sorted(nodes)


def plan(root=ROOT):
    manifest = json.loads((root / 'scripts/native-lanes.json').read_text())
    result = {'schema_version': 1, 'selections': manifest['selections'], 'checks': manifest['checks']}
    for selection in result['selections']:
        selection['check_operations'] = {
            name: {**operation, 'requirements': [
                path.format(runtime=selection['topology']['runtime'])
                for path in operation['requirements']]}
            for name, operation in manifest['selection_check_operations'].items()}
        selection['check_operations']['python-lint'] = selection.pop('lint_operation')
        selection['requirement_inventory'] = {
            name: [line.split('#', 1)[0].strip() for line in (root / name).read_text().splitlines()
                   if line.split('#', 1)[0].strip()]
            for name in selection['check_operations']['dependency-pins']['requirements']}
        for entries in selection['requirement_inventory'].values():
            for entry in entries:
                requirement = Requirement(entry)
                if requirement.url or requirement.marker:
                    raise ValueError('Unsupported requirement form')
        selection['expected_nodes'] = expected_nodes(root, selection['topology']['test_roots'])
        for proof in selection['topology']['required_proofs']:
            proof_nodes = expected_nodes(root, [proof])
            if not proof_nodes or not set(proof_nodes).issubset(selection['expected_nodes']):
                raise ValueError('Required proof has no covered test definitions: ' + proof)
        selection['source_fingerprint'] = fingerprint(root, selection['sources'])
        selection['dependency_fingerprint'] = fingerprint(root, manifest['dependencies'])
        selection['request_fingerprint'] = digest(selection)
    result['shared_source_fingerprint'] = fingerprint(root, ['web', 'tests/lanes', 'infra/foundation',
                                                           'scripts/native-lanes.py',
                                                           'scripts/native-lanes.json'])
    result['fingerprint'] = digest(result)
    return result


def validate_collection(selection, collection):
    """Validate the separately retained complete pre-execution collection response."""
    if not isinstance(collection, dict):
        raise ValueError('Missing collection evidence')
    for key, expected in [('schema_version', 1), ('request_fingerprint', selection['request_fingerprint']),
                          ('lifecycle_policy', selection['topology']['lifecycle_policy']),
                          ('complete', True)]:
        if collection.get(key) != expected:
            raise ValueError('Invalid collection evidence')
    nodes = collection.get('collected_nodeids')
    if (not isinstance(nodes, list) or not nodes
            or any(not isinstance(node, str) or not node for node in nodes)
            or len(set(nodes)) != len(nodes)):
        raise ValueError('Invalid complete collection inventory')
    for proof in selection['topology']['required_proofs']:
        prefix = proof + '::' if proof.endswith('.py') else proof.rstrip('/') + '/'
        if not any(node.startswith(prefix) for node in nodes):
            raise ValueError('Required proof omitted: ' + proof)
    for expected in selection['expected_nodes']:
        if not any(node == expected or node.startswith(expected + '[') for node in nodes):
            raise ValueError('Incomplete collection evidence')


def validate_record(selection, record, collection=None):
    """Reject incomplete, stale, skipped, or numerically inconsistent success claims.

    Required fields: schema_version, selection_id, request_fingerprint,
    source_fingerprint, dependency_fingerprint, topology, counts, skips,
    checks, collected_nodeids, nodes, result. Nodes contain canonical repository nodeid/outcome. Counts contain collected/passed/failed/errors/skipped.
    Skips contain nodeid/reason/required and must account for every skipped test.
    Required skips always fail completion, including opt-in lifecycle proofs.
    """
    validate_collection(selection, collection)
    if not isinstance(record, dict):
        raise ValueError('Invalid record')
    for key, expected in [('schema_version', 1), ('selection_id', selection['id']),
                          ('result', 'passed'), ('topology', selection['topology'])]:
        if record.get(key) != expected:
            raise ValueError('Invalid ' + key)
    for key in ('request_fingerprint', 'source_fingerprint', 'dependency_fingerprint'):
        if record.get(key) != selection[key]:
            raise ValueError('Stale ' + key)
    counts = record.get('counts', {})
    names = ('collected', 'passed', 'failed', 'errors', 'skipped')
    if not isinstance(counts, dict) or set(counts) != set(names) or any(type(counts[n]) is not int or counts[n] < 0 for n in names):
        raise ValueError('Invalid counts')
    if counts['collected'] == 0 or counts['collected'] != sum(counts[n] for n in names[1:]):
        raise ValueError('Incomplete collection')
    if counts['failed'] or counts['errors']:
        raise ValueError('Unsuccessful collection')
    skips = record.get('skips')
    if not isinstance(skips, list) or len(skips) != counts['skipped']:
        raise ValueError('Missing skip detail')
    for skip in skips:
        if (not isinstance(skip, dict) or set(skip) != {'nodeid', 'reason', 'required'} or not skip['nodeid']
                or not skip['reason'] or skip['required'] is not False
                or skip['nodeid'] not in selection['optional_skips']):
            raise ValueError('Required proof skipped')
    nodes = record.get('nodes')
    if not isinstance(nodes, list) or len(nodes) != counts['collected']:
        raise ValueError('Missing collection inventory')
    collected = record.get('collected_nodeids')
    if (not isinstance(collected, list) or any(not isinstance(n, str) for n in collected)
            or len(set(collected)) != len(collected)):
        raise ValueError('Missing exact collection inventory')
    if (set(collected) != set(collection['collected_nodeids'])
            or record.get('collection_fingerprint') != digest(collection)):
        raise ValueError('Complete collection differs')
    observed = {}
    for node in nodes:
        if (not isinstance(node, dict) or set(node) != {'nodeid', 'outcome'}
                or not isinstance(node['nodeid'], str) or not node['nodeid']
                or node['outcome'] not in ('passed', 'failed', 'errors', 'skipped')
                or node['nodeid'] in observed):
            raise ValueError('Invalid collection inventory')
        observed[node['nodeid']] = node['outcome']
    if set(observed) != set(collected):
        raise ValueError('Collected tests omitted')
    for outcome in ('passed', 'failed', 'errors', 'skipped'):
        if sum(value == outcome for value in observed.values()) != counts[outcome]:
            raise ValueError('Collection counts differ')
    for expected in selection['expected_nodes']:
        matching = [outcome for nodeid, outcome in observed.items()
                    if nodeid == expected or nodeid.startswith(expected + '[')]
        if not matching or any(outcome != 'passed' for outcome in matching):
            raise ValueError('Required test omitted')
    if record.get('checks') != {name: 'passed' for name in selection['checks']}:
        raise ValueError('Missing checks')

    evidence = record.get('check_execution')
    expected = {name: {'operation': operation, 'exit_code': 0,
                       'phase': 'before-tests',
                       'dependency_fingerprint': selection['dependency_fingerprint']}
                for name, operation in selection['check_operations'].items()}
    if not isinstance(evidence, dict) or set(evidence) != set(expected):
        raise ValueError('Missing dependency execution evidence')
    for name, required in expected.items():
        detail = evidence[name]
        extra = {'requirements'} if name == 'dependency-pins' else {'executed_argv'}
        if not isinstance(detail, dict) or set(detail) != {*required, *extra}:
            raise ValueError('Missing dependency execution detail')
        if any(detail[key] != value for key, value in required.items()):
            raise ValueError('Invalid dependency execution evidence')
        if name == 'python-lint':
            if detail['executed_argv'] != required['operation']['argv']:
                raise ValueError('Incomplete lint target execution')
            continue
        requirements = detail['requirements']
        if not isinstance(requirements, dict) or set(requirements) != set(required['operation']['requirements']):
            raise ValueError('Missing requirement files')
        for path, entries in requirements.items():
            if not isinstance(entries, list) or not entries:
                raise ValueError('Missing installed versions')
            for entry in entries:
                if (not isinstance(entry, dict)
                        or set(entry) != {'requirement', 'installed_version', 'satisfied'}
                        or any(not isinstance(entry[key], str) or not entry[key].strip()
                               for key in ('requirement', 'installed_version'))
                        or entry['satisfied'] is not True):
                    raise ValueError('Unsatisfied requirement')
                try:
                    requirement = Requirement(entry['requirement'])
                    installed = Version(entry['installed_version'])
                except (InvalidRequirement, InvalidVersion) as error:
                    raise ValueError('Invalid requirement version') from error
                if installed not in requirement.specifier:
                    raise ValueError('Installed version outside requirement')
            if sorted(entry['requirement'] for entry in entries) != sorted(selection['requirement_inventory'][path]):
                raise ValueError('Incomplete requirement coverage')


def validate_all(request, records, checks, collections=None):
    if set(records) != {s['id'] for s in request['selections']}:
        raise ValueError('Missing or extra selection')
    if not isinstance(collections, dict) or set(collections) != set(records):
        raise ValueError('Missing collection evidence')
    for selection in request['selections']:
        validate_record(selection, records[selection['id']], collections[selection['id']])
    if checks != {check['id']: 'passed' for check in request['checks']}:
        raise ValueError('Missing shared checks')


def run_provider(argv, *, check, timeout):
    """Bound one exchange and reap its process group on timeout or cancellation."""
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
    try:
        process = subprocess.Popen(argv, start_new_session=True)
    except BaseException:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        raise
    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        code = process.wait(timeout=timeout)
        if check and code:
            raise subprocess.CalledProcessError(code, argv)
    finally:
        # Finish bounded cleanup before delivering another termination request.
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTERM})
        try:
            # Also remove descendants left behind by a completed provider.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=CLEANUP_TIMEOUT_SECONDS)
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)


def exchange(provider, request, directory, name, runner):
    source = directory / (name + '-request.json')
    target = directory / (name + '-result.json')
    source.write_text(json.dumps(request, indent=2) + '\n')
    if target.exists():
        target.unlink()
    previous_handler = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        # Allow cleanup to finish even if termination is requested again.
        signal.signal(signum, signal.SIG_IGN)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    try:
        runner([sys.executable, str(provider), '--request', str(source), '--result', str(target)],
               check=True, timeout=PROVIDER_TIMEOUT_SECONDS)
        result = json.loads(target.read_text())
        if not isinstance(result, dict):
            raise ValueError('Invalid provider result')
        return result
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_handler)


def execute(request, directory, layout_provider, collection_provider, runner=run_provider):
    directory.mkdir(parents=True, exist_ok=False)
    records = {}
    collections = {}
    failures = {}
    for selection in request['selections']:
        try:
            layout = exchange(layout_provider, selection, directory, selection['id'] + '-layout', runner)
            if (layout.get('schema_version') != 1 or layout.get('read_only') is not True
                    or layout.get('request_fingerprint') != selection['request_fingerprint']):
                raise ValueError('Invalid read-only layout')
            collection = exchange(collection_provider, {
                'schema_version': 1, 'operation': 'collect', 'selection': selection,
                'layout': layout}, directory, selection['id'] + '-collection', runner)
            validate_collection(selection, collection)
            collections[selection['id']] = collection
            record = exchange(collection_provider, {'schema_version': 1, 'operation': 'execute',
                              'selection': selection, 'layout': layout,
                              'collection': collection, 'collection_fingerprint': digest(collection)},
                              directory, selection['id'], runner)
            records[selection['id']] = record
            validate_record(selection, record, collection)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failures[selection['id']] = type(error).__name__
    checks = {}
    try:
        response = exchange(collection_provider, {'schema_version': 1, 'checks': request['checks'],
                            'request_fingerprint': request['fingerprint']}, directory, 'shared', runner)
        if response.get('request_fingerprint') != request['fingerprint']:
            raise ValueError('Stale shared checks')
        checks = response['checks']
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        failures['shared'] = type(error).__name__
    try:
        validate_all(request, records, checks, collections)
    except ValueError:
        failures['coverage'] = 'Incomplete required coverage'
    summary = {'schema_version': 1, 'plan_fingerprint': request['fingerprint'],
               'records': records, 'collections': collections, 'checks': checks, 'failures': failures,
               'result': 'failed' if failures else 'passed'}
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all', action='store_true', required=True)
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--require-all', action='store_true',
                        help='Require complete evidence (also the default; partial success is never accepted)')
    parser.add_argument('--layout-provider', type=Path)
    parser.add_argument('--collection-provider', type=Path)
    args = parser.parse_args(argv)
    request = plan()
    if args.plan:
        print(json.dumps(request, indent=2))
        return 0
    if not args.run_dir:
        parser.error('--run-dir is required for execution')
    directory = args.run_dir.resolve()
    if directory == ROOT or ROOT in directory.parents:
        parser.error('--run-dir must be outside the source tree')
    if not args.layout_provider or not args.collection_provider:
        print('Native layout and collection providers are required; connected proof deferred.', file=sys.stderr)
        return 2
    summary = execute(request, directory, args.layout_provider.resolve(), args.collection_provider.resolve())
    return 1 if summary['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
