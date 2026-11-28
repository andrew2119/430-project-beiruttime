"""Run one part of a connected stage against this job's own stack and report each named step.

Usage: python .github/ci/stage.py <part> <report.json>

The parts are listed in required.json under stages: native; smokes, origin-proof and
proxy-proof; browser-desktop and browser-phone; scenarios-e06, scenarios-e04 and
scenarios-e09. Each part runs its own share of its stage's steps, and no step runs in two parts.
Every part starts the nine services and the production web from the build artifact, runs its
steps (each one runs even if an earlier one failed), stops the stack and checks that every
port is free again.

The smokes part runs the connected walkthrough through walkthrough.py, which answers a
possession review hold with scripted test inputs: not physical inspection. When the smokes part
fails, the walkthrough's publication child records are printed, their six known fields only.
Each browser part gives the browser its own temporary folder; when its step fails, the names
left in that folder and the Chrome processes still running are printed.
"""
import json
import os
from pathlib import Path
import socket
import stat
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


SCRIPTED_WALKTHROUGH = 'connected walkthrough, scripted possession review (not physical inspection)'
# The fields of a publication child record; nothing else in one is printed.
RECORD_FIELDS = ('exit_code', 'timed_out', 'exception_type', 'failure_category', 'http_status', 'upstream')
LISTED = 200

PARTS = ('native', 'smokes', 'origin-proof', 'proxy-proof', 'browser-desktop', 'browser-phone', 'scenarios-e06',
         'scenarios-e04', 'scenarios-e09')


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def browser_temp(part):
    return work_dir(f'tmp-{part}')


def browser_leftovers(folder):
    """Print the names left in the browser's temporary folder and the Chrome processes still running."""
    print('::group::browser leftovers', flush=True)
    try:
        names = []
        for top, folders, files in os.walk(folder):
            base = Path(top).relative_to(folder)
            names += [f'{base / name}/' for name in sorted(folders)] + [str(base / name) for name in sorted(files)]
        print(f'{len(names)} names left in the browser temporary folder', flush=True)
        for name in names[:LISTED]:
            print(f'  {name}', flush=True)
        if len(names) > LISTED:
            print(f'  ... and {len(names) - LISTED} more', flush=True)
    except Exception as error:
        print(f'Could not list the browser temporary folder: {error}', flush=True)
    try:
        table = subprocess.run(['ps', '-eo', 'pid=,ppid=,stat=,etime=,comm=,args='], capture_output=True, text=True,
                               timeout=15).stdout
        rows = []
        for line in table.splitlines():
            fields = line.split(None, 5)
            if len(fields) >= 5 and fields[4].startswith('chrome'):
                kind = next((arg.split('=', 1)[1] for arg in (fields[5] if len(fields) > 5 else '').split()
                             if arg.startswith('--type=')), 'browser')
                rows.append(f'  pid {fields[0]} parent {fields[1]} state {fields[2]} running {fields[3]} '
                            f'{fields[4]} ({kind})')
        print(f'{len(rows)} Chrome processes still running', flush=True)
        for row in rows[:LISTED]:
            print(row, flush=True)
    except Exception as error:
        print(f'Could not list the running processes: {error}', flush=True)
    print('::endgroup::', flush=True)


def publication_records(run):
    """Print each publication child record the walkthrough left in the run, its six known fields only."""
    print('::group::publication child records', flush=True)
    try:
        records = sorted(run.glob('publication-child-*.json'))
        if not records:
            print('No publication child record in this run.', flush=True)
        for path in records:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                print(f'{path.name}: not a plain file of at most 4096 bytes; not read', flush=True)
                continue
            try:
                record = json.loads(path.read_bytes())
            except ValueError:
                print(f'{path.name}: not JSON', flush=True)
                continue
            if not isinstance(record, dict):
                print(f'{path.name}: not a JSON object', flush=True)
                continue
            shown = {field: record[field] for field in RECORD_FIELDS if field in record}
            other = sorted(set(record) - set(RECORD_FIELDS))
            print(f'{path.name}: {json.dumps(shown)}' + (f'; other fields, values not shown: {", ".join(other)}'
                                                          if other else ''), flush=True)
    except Exception as error:
        print(f'Could not read the publication child records: {error}', flush=True)
    print('::endgroup::', flush=True)


def steps(part, run):
    """The ordered (name, command, seconds, extra environment) steps of each part."""
    browser = ['node', '.github/ci/browser.mjs', str(run / 'browser.json')]

    def browser_env():
        # Called only by the browser parts, so no other part makes a browser temporary folder.
        return dict(TMPDIR=str(browser_temp(part)))

    scenarios = work_dir('scenarios')
    parts = {
        'native': lambda: [('readiness', 'ready', 30, {})],
        'smokes': lambda: [
            ('http smokes', 'smokes', 60, {}),
            (SCRIPTED_WALKTHROUGH, [PYTHON, '.github/ci/walkthrough.py', str(run), 'http://localhost:3000'], 620, {}),
        ],
        # Each proof copies the tree and makes its own production web build first.
        'origin-proof': lambda: [('origin proof', [PYTHON, 'scripts/native-origin-proof.py', '--run-dir', str(run),
                                                   '--origin', f'http://localhost:{free_port()}'], 600, N07_ENV)],
        'proxy-proof': lambda: [('proxy proof', [PYTHON, 'scripts/native-proxy-proof.py', '--run-dir', str(run),
                                                 '--origin', f'http://localhost:{free_port()}', '--loopback'], 600,
                                 N07_ENV)],
        'browser-desktop': lambda: [('browser desktop matrix and screenshots', [*browser, 'desktop'], 300,
                                     browser_env())],
        'browser-phone': lambda: [('browser phone matrix and screenshots', [*browser, 'phone'], 300, browser_env())],
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
                if part.startswith('browser-'):
                    browser_leftovers(browser_temp(part))
        if part == 'smokes' and problems:
            publication_records(run)
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
