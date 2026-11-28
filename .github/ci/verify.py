"""Check that every required job ran, passed and reported every required test exactly once.

Usage: python3 .github/ci/verify.py <full|light> <needs.json> <reports-folder>

needs.json is the workflow's toJSON(needs); the reports folder holds each suite's one-line
report (<suite>.json) as the jobs uploaded them. The pinned lists live in required.json.
It prints one line per suite, and per web suite, with its counts and the sha256 of its sorted test
identities, then the tested tree, so two runs of the same tree can be compared suite by suite.

A job passes only when its own runner exited 0 (its result is success), its report exists and
says ok, and the report shows every required test or step ran and passed, nothing skipped:
  - each of the nine services and the integration lanes collected and passed the same tests,
    and at least every test their files declare;
  - the Vitest shards together listed every web suite of this tree once, every part of every
    suite ran once, and the tests they ran add up to exactly the listed tests, by count and by
    an order-independent identity sum;
  - each pinned web gap was reported skipped exactly once, and no other test was skipped;
  - every stage part reports exactly its pinned steps, no step ran in two parts, and the browser
    parts together ran every pinned browser check exactly once.
In light mode only the suites the plan reached are required; the others must be skipped.
"""
from collections import Counter
import json
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_ci import NAMES  # noqa: E402
import vitest  # noqa: E402

HERE = Path(__file__).resolve().parent
REQUIRED = vitest.REQUIRED
# Steps every stage part reports for itself; the rest belong to exactly one part.
OWN_STEPS = {'stack start', 'stack stop', 'browser report'}


def stage_parts():
    return [part for parts in REQUIRED['stages'].values() for part in parts]


def expected_reports(mode, plan):
    if mode == 'full':
        services, web, lanes, stages = REQUIRED['services'], True, True, True
    else:
        services, web, lanes, stages = plan['services'], plan['web'], plan['lanes'], False
    names = list(services)
    if lanes:
        names.append('lanes')
    if web:
        names += ['web', *(f"shard{i}" for i in range(1, REQUIRED['vitest_shards'] + 1))]
    if stages:
        names += ['images', *stage_parts(), 'n01']
    return names


def check_pins():
    """required.json must name every service of the tree, so a new one can never go untested."""
    if REQUIRED['services'] != NAMES:
        return [f"required.json services {REQUIRED['services']} differ from the tree's {NAMES}"]
    return []


def check_jobs(mode, needs, plan):
    problems = []
    for job in REQUIRED['jobs'][mode]:
        result = needs.get(job, {}).get('result', 'missing')
        reached = True
        if mode == 'light' and job != 'plan':
            reached = {'services': bool(plan['services']), 'lanes': plan['lanes'], 'web': plan['web'],
                       'vitest': plan['web']}[job]
        if reached and result != 'success':
            problems.append(f'job {job}: {result}')
        if not reached and result not in ('skipped', 'success'):
            problems.append(f'job {job}: {result} though the plan did not reach it')
    return problems


def check_tests(name, report):
    problems = []
    collected, passed, floor = report.get('collected', 0), report.get('passed', 0), report.get('floor', 0)
    if not (collected == passed > 0 and floor <= collected and len(report.get('ids_sha256', '')) == 64):
        problems.append(f'{name}: collected {collected}, passed {passed}, declared {floor}')
    return problems


def check_stages(reports):
    """No step ran in two parts of a stage, and the browser parts ran every pinned check once."""
    problems = []
    for stage, parts in REQUIRED['stages'].items():
        seen = Counter(step for part in parts for step in reports.get(part, {}).get('steps', [])
                       if step not in OWN_STEPS)
        twice = sorted(step for step, n in seen.items() if n > 1)
        if twice:
            problems.append(f'{stage}: steps reported by more than one part: {twice}')
    checks = Counter(check for part in REQUIRED['stages']['browser']
                     for check in reports.get(part, {}).get('checks', []))
    wanted = Counter(REQUIRED['browser_checks'])
    if checks != wanted:
        problems.append(f'browser: checks missing {sorted(wanted - checks)}, repeated or unexpected '
                        f'{sorted(checks - wanted)}')
    return problems, sum(checks.values())


def check_vitest(reports):
    """Every web suite listed once, every part of it run once, and the parts add up to the listing."""
    shards = REQUIRED['vitest_shards']
    problems, units, listings, rows = [], {}, {}, []
    for i in range(1, shards + 1):
        shard = reports.get(f'shard{i}', {})
        if shard.get('total') != shards or shard.get('shard') != i:
            problems.append(f'shard{i}: reports shard {shard.get("shard")} of {shard.get("total")}')
        for unit in shard.get('units', []):
            units.setdefault(unit.get('config'), []).append(unit)
        for config, listing in shard.get('listings', {}).items():
            listings.setdefault(config, []).append(listing)
    wanted = [config for config, _ in vitest.configs()]
    missing, extra = sorted(set(wanted) - set(units)), sorted((set(units) | set(listings)) - set(wanted))
    if missing or extra:
        problems.append(f'web suites missing {missing[:5]}, unexpected {extra[:5]}')
    skipped = Counter()
    for config in wanted:
        parts, found = units.get(config, []), listings.get(config, [])
        counts = sorted({u.get('parts') for u in parts}, key=str)
        numbers = sorted((u.get('part') for u in parts), key=str)
        complete = len(counts) == 1 and isinstance(counts[0], int) and numbers == list(range(1, counts[0] + 1))
        if not complete or len(found) != 1:
            problems.append(f'{config}: ran parts {numbers} of {counts}, listed in {len(found)} shards')
            rows.append((config, 'failed', f'ran parts {numbers} of {counts}, listed in {len(found)} shards'))
            continue
        listed = found[0]
        ran = sum(u.get('ran', 0) for u in parts)
        total = sum(int(u.get('ran_sum', '0'), 16) for u in parts) % (1 << 256)
        skipped.update((config, name) for u in parts for name in u.get('skipped', []))
        same = format(total, 'x') == listed['listed_sum']
        good = ran == listed['listed'] and same and all('ran' in u and u.get('passed') == u['ran'] for u in parts)
        if any('ran' not in u or u.get('passed') != u.get('ran') for u in parts):
            problems.append(f'{config}: not every test passed')
        if ran != listed['listed'] or not same:
            problems.append(f"{config}: parts ran {ran} tests, listed {listed['listed']}, identities "
                            f"{'match' if same else 'differ'}")
        rows.append((config, 'ok' if good else 'failed',
                     f"{listed['listed']} listed, {ran} ran in {counts[0]} part(s), ids {listed.get('listed_sha256')}"))
    gaps = {(gap['config'], f"{gap['file']} > {gap['test']}"): gap for gap in REQUIRED['web_skip_gaps']}
    for config, name in sorted(skipped):
        if (config, name) not in gaps:
            problems.append(f'{config}: skipped {name}, which required.json does not pin')
    for key, gap in gaps.items():
        n = skipped[key]
        if n != 1:
            problems.append(f'{gap["config"]}: pinned gap {key[1]} reported skipped {n} times, not exactly once '
                            '(missing, passing, renamed or repeated)')
        rows.append((f'gap {key[1]}', 'NOT PASSED',
                     f"known gap, skipped {n} time(s) as pinned, never counted as passed: {gap['reason']}"))
    listed = sum(entry.get('listed', 0) for entries in listings.values() for entry in entries)
    rows.insert(0, ('web suites', 'ok' if not problems else 'failed',
                    f'{len(units)} suites, {listed} listed tests, {sum(skipped.values())} pinned gaps skipped'))
    return problems, rows


def git(*args, stdin=None):
    return subprocess.run(['git', '-C', str(HERE), *args], input=stdin, capture_output=True,
                          text=True).stdout.strip()


def tested_tree():
    """The tested commit, its tree, and its tree without .github, which commits differing only in CI files share."""
    # git runs inside .github/ci; --full-tree lists the whole commit tree, not just this folder.
    entries = git('ls-tree', '--full-tree', 'HEAD').splitlines()
    outside = git('mktree', stdin=''.join(e + '\n' for e in entries if e.split('\t', 1)[-1] != '.github'))
    return dict(head=git('rev-parse', 'HEAD'), tree=git('rev-parse', 'HEAD^{tree}'), tree_outside_ci=outside,
                workflow_commit=os.environ.get('GITHUB_SHA', ''))


def main(mode, needs_file, folder):
    needs = json.loads(Path(needs_file).read_text())
    plan = {}
    if mode == 'light':
        plan = json.loads(needs.get('plan', {}).get('outputs', {}).get('plan') or '{}')
        if not plan:
            print('The plan job published no plan.')
            return 1
    problems = check_pins() + check_jobs(mode, needs, plan)
    reports, rows = {}, []
    for name in expected_reports(mode, plan):
        path = Path(folder) / f'{name}.json'
        try:
            report = json.loads(path.read_text().splitlines()[0])
        except (OSError, ValueError, IndexError):
            problems.append(f'{name}: no report')
            rows.append((name, 'missing', ''))
            continue
        reports[name] = report
        if report.get('suite') != name or report.get('ok') is not True:
            problems.append(f"{name}: not ok: {report.get('problems', [])[:3]}")
        if name in REQUIRED['services'] or name == 'lanes':
            problems += check_tests(name, report)
            detail = (f"{report.get('passed')} passed of {report.get('collected')}, {report.get('floor')} declared, "
                      f"ids {report.get('ids_sha256')}")
        elif name in REQUIRED['steps']:
            steps = report.get('steps', [])
            if steps != REQUIRED['steps'][name]:
                missing = [s for s in REQUIRED['steps'][name] if s not in steps]
                problems.append(f'{name}: steps {steps}, missing {missing}')
            detail = f"{len(steps)} of {len(REQUIRED['steps'][name])} steps"
            if 'checks' in report:
                detail += f", checks {report['checks']}"
        else:
            units = report.get('units', [])
            detail = f"{sum(u.get('ran', 0) for u in units)} tests in {len(units)} parts"
        rows.append((name, 'ok' if report.get('ok') is True else 'failed', detail))
    if mode == 'full':
        found, checks = check_stages(reports)
        problems += found
        rows.append(('stage parts', 'ok' if not found else 'failed',
                     f'{len(stage_parts())} parts, {checks} browser checks'))
    if any(name.startswith('shard') for name in expected_reports(mode, plan)):
        found, web_rows = check_vitest(reports)
        problems += found
        rows += web_rows
    tree = tested_tree()
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as out:
            title = 'Full suite' if mode == 'full' else 'Light check (not the full suite)'
            out.write(f'### {title}\n\n| Suite | Result | Detail |\n| --- | --- | --- |\n')
            out.writelines(f'| {n} | {r} | {d} |\n' for n, r, d in rows)
            out.write(f"\nTested commit `{tree['head']}`, tree `{tree['tree']}`, tree without .github "
                      f"`{tree['tree_outside_ci']}`, CI files from `{tree['workflow_commit']}`.\n")
            if problems:
                out.write('\n**Problems**\n\n' + ''.join(f'- {p}\n' for p in problems[:50]))
    for name, result, detail in rows:
        print(f'{result:10} {name}: {detail}')
    for problem in problems:
        print(f'::error::{problem}')
    print(json.dumps(dict(mode=mode, ok=not problems, suites=len(rows), problems=len(problems), **tree)))
    return 0 if not problems else 1


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] not in ('full', 'light'):
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:]))
