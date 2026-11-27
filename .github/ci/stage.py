"""Run one part of a connected stage against this job's own stack and report each named step.

Usage: python .github/ci/stage.py <part> <report.json>

The parts are listed in required.json under stages: native; smokes, origin-proof and
proxy-proof; browser-desktop and browser-phone; scenarios-e06, scenarios-e04 and
scenarios-e09. Each part runs its own share of its stage's steps, and no step runs in two parts.
Every part starts the nine services and the production web from the build artifact, runs its
steps (each one runs even if an earlier one failed), stops the stack and checks that every
port is free again.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_ci import ROOT, SHARED, common_environment, write_report, work_dir  # noqa: E402
import checks_http  # noqa: E402
import stack  # noqa: E402

PYTHON = sys.executable
N07_ENV = dict(COREPACK_ENABLE_NETWORK='0', COREPACK_ENABLE_AUTO_PIN='0', COREPACK_DEFAULT_TO_LATEST='0',
               COREPACK_ENABLE_PROJECT_SPEC='1', COREPACK_ENABLE_STRICT='1',
               npm_config_manage_package_manager_versions='false', npm_config_offline='true')


PARTS = ('native', 'smokes', 'origin-proof', 'proxy-proof', 'browser-desktop', 'browser-phone', 'scenarios-e06',
         'scenarios-e04', 'scenarios-e09')


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def steps(part, run):
    """The ordered (name, command, seconds, extra environment) steps of each part."""
    walk = ROOT / 'tests/integration/sprint-1/connected_walkthrough.py'
    browser = ['node', '.github/ci/browser.mjs', str(run / 'browser.json')]
    scenarios = work_dir('scenarios')
    parts = {
        'native': lambda: [('readiness', 'ready', 30, {})],
        'smokes': lambda: [
            ('http smokes', 'smokes', 60, {}),
            ('connected walkthrough', [PYTHON, str(walk), 'all', '--backend', 'native', '--run-dir', str(run),
                                       '--origin', 'http://localhost:3000'], 620, {}),
        ],
        # Each proof copies the tree and makes its own production web build first.
        'origin-proof': lambda: [('origin proof', [PYTHON, 'scripts/native-origin-proof.py', '--run-dir', str(run),
                                                   '--origin', f'http://localhost:{free_port()}'], 600, N07_ENV)],
        'proxy-proof': lambda: [('proxy proof', [PYTHON, 'scripts/native-proxy-proof.py', '--run-dir', str(run),
                                                 '--origin', f'http://localhost:{free_port()}', '--loopback'], 600,
                                 N07_ENV)],
        'browser-desktop': lambda: [('browser desktop matrix and screenshots', [*browser, 'desktop'], 300, {})],
        'browser-phone': lambda: [('browser phone matrix and screenshots', [*browser, 'phone'], 300, {})],
        'scenarios-e06': lambda: [
            ('E06 contract tests', [PYTHON, '-m', 'unittest', 'discover', '-s', 'tests/integration/sprint-2',
                                    '-p', 'test_*.py', '-v'], 120, {}),
            ('E06 preparation manifest', ['bash', '-c', '"$1" "$2" > "$3"', '_', PYTHON,
                                          'tests/integration/sprint-2/proof.py', str(scenarios / 'preparation.json')],
             15, {}),
        ],
        'scenarios-e04': lambda: [
            ('E04 synthetic restore', ['bash', '-c', '"$1" "$2" > "$3"', '_', PYTHON, 'tests/lanes/L24/E04/run.py',
                                       str(scenarios / 'synthetic-result.json')], 150,
             dict(TMPDIR=str(scenarios), PYTEST_ADDOPTS=f'--basetemp={scenarios}/pytest')),
        ],
        'scenarios-e09': lambda: [
            ('E09 rehearsal contract tests', [PYTHON, '-m', 'unittest', 'discover', '-s', 'tests/lanes/L22/E09',
                                              '-p', 'test_*.py', '-v'], 120, {}),
        ],
    }
    return parts[part]()


def execute(name, command, seconds, extra, env):
    print(f'::group::{name}', flush=True)
    started = time.monotonic()
    try:
        if command == 'ready':
            checks_http.ready(seconds)
            ok, detail = True, ''
        elif command == 'smokes':
            passed, problems = checks_http.smokes()
            ok, detail = not problems and len(passed) == 24, '; '.join(problems)
        else:
            code = subprocess.run(command, cwd=ROOT, env=dict(env, **extra), timeout=seconds).returncode
            ok, detail = code == 0, f'exit {code}'
    except subprocess.TimeoutExpired:
        ok, detail = False, f'timed out after {seconds}s'
    except Exception as error:
        ok, detail = False, str(error)
    print('::endgroup::', flush=True)
    seconds_taken = round(time.monotonic() - started, 1)
    print(f"{'PASS' if ok else 'FAIL'} {name} ({seconds_taken}s) {detail}", flush=True)
    return dict(step=name, ok=ok, seconds=seconds_taken, detail=detail[:300])


def main(part, report):
    if part not in PARTS:
        raise SystemExit(f'unknown stage part {part}')
    run = work_dir(f'run-{part}')
    results, problems, checks = [], [], []
    try:
        stack.start(run)
        results.append(dict(step='stack start', ok=True))
    except Exception as error:
        results.append(dict(step='stack start', ok=False, detail=str(error)[:300]))
        problems.append(f'stack start: {error}')
    if not problems:
        env = dict(os.environ, **common_environment(), PYTHONPATH=':'.join(map(str, [run / 'contracts', *SHARED])))
        for name, command, seconds, extra in steps(part, run):
            row = execute(name, command, seconds, extra, env)
            results.append(row)
            if not row['ok']:
                problems.append(f"{name}: {row['detail']}")
        if part.startswith('browser-') and (run / 'browser.json').is_file():
            browser = json.loads((run / 'browser.json').read_text())
            checks = browser.get('checks', [])
            results.append(dict(step='browser report', ok=browser.get('ok') is True))
    try:
        stack.stop(run)
        results.append(dict(step='stack stop', ok=True))
    except BaseException as error:
        results.append(dict(step='stack stop', ok=False, detail=str(error)[:300]))
        problems.append(f'stack stop: {error}')
    ok = not problems and all(row['ok'] for row in results)
    extra = dict(checks=checks) if part.startswith('browser-') else {}
    return write_report(report, part, ok, problems, steps=[r['step'] for r in results if r['ok']], **extra)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2]))
