"""Run the sprint-1 integration unit tests and check them against the statically declared cases.

Usage: python .github/ci/lanes.py <report.json>
"""
import ast
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_ci import ROOT, SHARED, common_environment, ids_digest, package_contracts, work_dir, write_report  # noqa: E402

FOLDER = ROOT / 'tests/integration/sprint-1'


class Cases(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.passed = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed.append(test.id())


def declared():
    ids = []
    for path in sorted(FOLDER.glob('test_*.py')):
        for node in ast.parse(path.read_bytes()).body:
            if isinstance(node, ast.ClassDef):
                ids.extend(f'{path.stem}.{node.name}.{m.name}' for m in node.body
                           if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name.startswith('test'))
    return sorted(ids)


def main(report):
    contracts = package_contracts(None, work_dir('lanes'))
    paths = [str(contracts), *map(str, SHARED)]
    os.environ.update(common_environment(), PYTHONPATH=':'.join(paths))
    sys.path[1:1] = paths
    os.chdir(ROOT)
    tests = unittest.defaultTestLoader.discover(str(FOLDER), pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=2, resultclass=Cases).run(tests)
    problems = [f'{kind}: {test.id()}' for kind, items in (
        ('failed', result.failures), ('error', result.errors), ('skipped', result.skipped),
        ('expected failure', result.expectedFailures)) for test, _ in items]
    problems += [f'unexpected success: {test.id()}' for test in result.unexpectedSuccesses]
    expected = declared()
    if sorted(set(result.passed)) != expected:
        problems.append(f'passed set differs from declared cases: {sorted(set(result.passed) ^ set(expected))[:5]}')
    ok = result.wasSuccessful() and result.testsRun == len(result.passed) > 0 and not problems
    return write_report(report, 'lanes', ok, problems, collected=result.testsRun, passed=len(result.passed),
                        floor=len(expected), ids_sha256=ids_digest(result.passed))


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
