"""Check that every required job ran, passed and reported every required test.

Usage: python3 .github/ci/verify.py <full|light> <needs.json> <reports-folder>

needs.json is the workflow's toJSON(needs); the reports folder holds each suite's one-line
report (<suite>.json) as the jobs uploaded them. The pinned lists live in required.json.

A job passes only when its own runner exited 0 (its result is success), its report exists and
says ok, and the report shows every required test or step ran and passed, nothing skipped:
  - each of the nine services and the integration lanes collected and passed the same tests,
    and at least every test their files declare;
  - the Vitest shards together listed every web suite of this tree once, and the tests they ran
    add up to exactly the listed tests, by count and by an order-independent identity sum;
  - every stage reports exactly its pinned steps.
In light mode only the suites the plan reached are required; the others must be skipped.
"""
import json
from pathlib import Path
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vitest  # noqa: E402

HERE = Path(__file__).resolve().parent
REQUIRED = json.loads((HERE / 'required.json').read_text())


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
        names += ['images', 'native', 'smokes', 'browser', 'scenarios', 'n01']
    return names


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


def check_vitest(reports):
    problems, merged = [], {}
    for i in range(1, REQUIRED['vitest_shards'] + 1):
        shard = reports.get(f'shard{i}', {})
        if shard.get('total') != REQUIRED['vitest_shards'] or shard.get('shard') != i:
            problems.append(f'shard{i}: reports shard {shard.get("shard")} of {shard.get("total")}')
        for config, entry in shard.get('suites', {}).items():
            merged.setdefault(config, []).append(entry)
    wanted = [config for config, _ in vitest.configs()]
    missing, extra = sorted(set(wanted) - set(merged)), sorted(set(merged) - set(wanted))
    if missing or extra:
        problems.append(f'web suites missing {missing[:5]}, unexpected {extra[:5]}')
    for config in wanted:
        entries = merged.get(config, [])
        listings = [e for e in entries if 'listed' in e]
        if len(entries) != REQUIRED['vitest_shards'] or len(listings) != 1:
            problems.append(f'{config}: ran in {len(entries)} shards, listed in {len(listings)}')
            continue
        listed = listings[0]
        ran = sum(e.get('ran', 0) for e in entries)
        total = sum(int(e.get('ran_sum', '0'), 16) for e in entries) % (1 << 256)
        if any(e.get('passed') != e.get('ran') for e in entries):
            problems.append(f'{config}: not every test passed')
        if ran != listed['listed'] or format(total, 'x') != listed['listed_sum']:
            problems.append(f"{config}: shards ran {ran} tests, listed {listed['listed']}, identities "
                            f"{'match' if format(total, 'x') == listed['listed_sum'] else 'differ'}")
    return problems, merged


def main(mode, needs_file, folder):
    needs = json.loads(Path(needs_file).read_text())
    plan = {}
    if mode == 'light':
        plan = json.loads(needs.get('plan', {}).get('outputs', {}).get('plan') or '{}')
        if not plan:
            print('The plan job published no plan.')
            return 1
    problems = check_jobs(mode, needs, plan)
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
            detail = f"{report.get('passed')} passed of {report.get('collected')}, {report.get('floor')} declared"
        elif name in REQUIRED['steps']:
            steps = report.get('steps', [])
            if steps != REQUIRED['steps'][name]:
                problems.append(f"{name}: steps {steps}, missing {[s for s in REQUIRED['steps'][name] if s not in steps]}")
            detail = f"{len(steps)} of {len(REQUIRED['steps'][name])} steps"
        else:
            detail = f"{sum(e.get('ran', 0) for e in report.get('suites', {}).values())} tests"
        rows.append((name, 'ok' if report.get('ok') is True else 'failed', detail))
    if any(name.startswith('shard') for name in expected_reports(mode, plan)):
        found, merged = check_vitest(reports)
        problems += found
        listed = sum(e.get('listed', 0) for entries in merged.values() for e in entries)
        rows.append(('web suites', 'ok' if not found else 'failed', f'{len(merged)} suites, {listed} listed tests'))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as out:
            title = 'Full suite' if mode == 'full' else 'Light check (not the full suite)'
            out.write(f'### {title}\n\n| Suite | Result | Detail |\n| --- | --- | --- |\n')
            out.writelines(f'| {n} | {r} | {d} |\n' for n, r, d in rows)
            if problems:
                out.write('\n**Problems**\n\n' + ''.join(f'- {p}\n' for p in problems[:50]))
    for name, result, detail in rows:
        print(f'{result:8} {name}: {detail}')
    for problem in problems:
        print(f'::error::{problem}')
    print(json.dumps(dict(mode=mode, ok=not problems, suites=len(rows), problems=len(problems))))
    return 0 if not problems else 1


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] not in ('full', 'light'):
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:]))
