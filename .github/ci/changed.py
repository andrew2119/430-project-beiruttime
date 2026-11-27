"""Map a pull request's changed paths to the light-check suites they reach.

Usage: python3 .github/ci/changed.py [--all] [path ...]

With no paths it reads the change from git: the files that differ between the pull request's
merge commit (HEAD) and its first parent, the tip of the base branch. The checkout needs a
fetch depth of 2 for that parent to be present.

The light suites are: web (lint, types, the money format test and every web Vitest suite),
each of the nine services, and the sprint-1 integration lanes. The first matching rule wins.
Shared code, lockfiles, the workflow and CI files, and every path no rule knows reach every
light suite, so an unmapped change can never shrink the check. Paths that only the full suite
covers (documentation, image and Compose files) reach none, and the change is then checked by
the plan alone; the full Tests run on a group pull request or on main still covers them.

Writes services (a JSON list), web and lanes (true or false) and plan (the whole result as
JSON) to GITHUB_OUTPUT when that is set, and a table of reasons to the job summary.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SERVICES = [s['name'] for s in json.loads((ROOT / 'scripts/native-services.json').read_text())['services']
            if s['name'] != 'web']
ALL = ('all',)
EVERY_SERVICE = tuple(f'service:{name}' for name in SERVICES)
WEB = ('web',)
LANES = ('lanes',)
NONE = ()

# (prefix or exact path, suites). A prefix ends with '/'.
RULES = [
    # Shared code and settings every suite builds on.
    ('.github/', ALL), ('packages/', ALL), ('contracts/', ALL), ('scripts/native-services.json', ALL),
    ('infra/foundation/', ALL), ('package.json', ALL), ('pnpm-lock.yaml', ALL), ('pnpm-workspace.yaml', ALL),
    ('tsconfig.base.json', ALL), ('.gitignore', ALL), ('.dockerignore', ALL),
    # One service's own code and tests reach that service; the template reaches every service.
    ('services/_template/', EVERY_SERVICE),
    *((f'services/{name}/', (f'service:{name}',)) for name in SERVICES),
    # Tests the service suites collect from outside the service folders.
    ('tests/foundation/', EVERY_SERVICE), ('tests/lanes/L00/', EVERY_SERVICE),
    # The web app, and the lane suites that test it.
    ('web/', WEB), ('tests/lanes/L04/', WEB), ('tests/lanes/L07/', WEB), ('tests/lanes/L08/', WEB),
    ('tests/lanes/L09/', WEB), ('tests/lanes/L11/', WEB),
    # The sprint-1 integration lanes.
    ('tests/integration/sprint-1/', LANES),
    # Covered only by the full suite.
    ('docs/', NONE), ('README.md', NONE), ('infra/compose/', NONE), ('compose.yaml', NONE), ('Makefile', NONE),
    ('.railway/', NONE),
]


def reach(path):
    for rule, suites in RULES:
        if path == rule or (rule.endswith('/') and path.startswith(rule)):
            return rule, suites
    return 'not in the map', ALL


def git_changes():
    try:
        out = subprocess.run(['git', '-C', str(ROOT), 'diff', '--name-only', '--no-renames', 'HEAD^1', 'HEAD'],
                             check=True, capture_output=True, text=True).stdout
    except subprocess.CalledProcessError:
        return None
    return [line for line in out.splitlines() if line]


def plan(paths):
    rows, suites = [], set()
    if paths is None:
        rows.append(('(the change could not be read)', 'fallback', ALL))
        suites.update(ALL)
    for path in paths or []:
        rule, reached = reach(path)
        rows.append((path, rule, reached))
        suites.update(reached)
    if 'all' in suites:
        suites = {'web', 'lanes', *EVERY_SERVICE}
    result = dict(services=[name for name in SERVICES if f'service:{name}' in suites], web='web' in suites,
                  lanes='lanes' in suites, changed=len(paths or []))
    return result, rows


def main(args):
    if args[:1] == ['--all']:
        result, rows = plan(None)
        rows[0] = ('(every light suite requested)', 'all', ALL)
    else:
        result, rows = plan(args or git_changes())
    line = json.dumps(result, separators=(',', ':'))
    print(line)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
            out.write(f"services={json.dumps(result['services'], separators=(',', ':'))}\n")
            out.write(f"web={str(result['web']).lower()}\nlanes={str(result['lanes']).lower()}\nplan={line}\n")
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as out:
            out.write('### Light check plan\n\n| Changed path | Rule | Reaches |\n| --- | --- | --- |\n')
            for path, rule, reached in rows[:200]:
                out.write(f"| `{path}` | `{rule}` | {', '.join(reached) or 'full suite only'} |\n")
            if len(rows) > 200:
                out.write(f'\n{len(rows) - 200} more paths not listed.\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
