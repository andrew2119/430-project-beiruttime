"""Run one shard of the web Vitest suites and report per suite.

Usage: python .github/ci/vitest.py <shard> <total> <report.json> [config ...]

plan() splits the suites across the shards the same way on every runner. A small suite runs
whole in one shard; a large one is cut into parts with Vitest's own --shard, and each part
runs in its own shard. Each suite is also listed once, unsharded, in the shard that runs its
first part, so the check job can prove the parts together ran exactly the listed tests: their
counts add up and the order-independent sums of their test identities match the listed set.

A test may be skipped only when required.json pins it as a known gap, by suite, file and full
title. A pinned skip is reported by name under skipped and never counts as run or passed.
Any other skipped, pending, todo or failed test is a failure.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_ci import ROOT, write_report, work_dir  # noqa: E402

WEB = ROOT / 'web'
VITEST = WEB / 'node_modules/.bin/vitest'
REQUIRED = json.loads((Path(__file__).resolve().parent / 'required.json').read_text())
TEST_FILE = re.compile(r'.+\.(test|spec)\.[cm]?[jt]sx?$')
SKIP_DIRS = {'node_modules', '.next', 'dist', 'coverage'}
# A suite with more test files than this is cut into parts, at most one part per shard.
PART_FILES = 12
# The fixed cost of starting one Vitest run, in test files, used only to balance the shards.
START_COST = 1


def configs():
    """Every web suite, in a fixed order: the app, each feature, then the lane suites."""
    found = [('web/vitest.config.ts', 'web')]
    found += [(p.relative_to(ROOT).as_posix(), 'web') for p in sorted((WEB / 'features').glob('*/vitest.config.ts'))]
    found += [('tests/lanes/L04/vitest.config.mts', 'web'), ('tests/lanes/L07/vitest.config.ts', '.'),
              ('tests/lanes/L08/web/vitest.config.ts', '.'), ('tests/lanes/L09/web/vitest.config.ts', 'web')]
    return found


def size(config, others):
    """Test files under the suite's folder, leaving out other suites' folders: a balancing estimate only.

    The proof never relies on it: Vitest's own --shard decides which files each part runs."""
    folder = (ROOT / config).parent
    nested = {(ROOT / other).parent for other in others} - {folder}
    count = 0
    for top, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and Path(top, d) not in nested)
        count += sum(1 for name in files if TEST_FILE.match(name))
    return count


def plan(total):
    """{shard: [(config, root, part, parts), ...]} for every suite, the same on every runner."""
    suites = configs()
    names = [config for config, _ in suites]
    units = []
    for config, root in suites:
        files = size(config, names)
        parts = max(1, min(total, -(-files // PART_FILES)))
        units += [(files / parts, config, root, part, parts) for part in range(1, parts + 1)]
    load = {shard: 0.0 for shard in range(1, total + 1)}
    shards = {shard: [] for shard in load}
    for weight, config, root, part, parts in sorted(units, key=lambda u: (-u[0], u[1], u[3])):
        shard = min(load, key=lambda s: (load[s], s))
        load[shard] += weight + START_COST
        shards[shard].append((config, root, part, parts))
    return shards


def identity(file, names):
    return Path(file).resolve().relative_to(ROOT).as_posix() + ' > ' + ' > '.join(names)


def pinned_skips(config):
    """The identities of the skips required.json allows in this suite."""
    return {f"{gap['file']} > {gap['test']}" for gap in REQUIRED['web_skip_gaps'] if gap['config'] == config}


def multiset(ids):
    """An order-independent sum of test identities that adds up across shards."""
    return sum(int(hashlib.sha256(i.encode()).hexdigest(), 16) for i in ids) % (1 << 256)


def run(command, log):
    with log.open('w') as stream:
        return subprocess.run(command, cwd=WEB, stdout=stream, stderr=subprocess.STDOUT).returncode


def tail(log, lines=40):
    text = log.read_text(errors='replace').splitlines()
    print('\n'.join(text[-lines:]))


def judge(config, data):
    """Read one Vitest JSON result: (unit fields, problems). Only pinned skips may be skipped."""
    allowed = pinned_skips(config)
    ids, skipped, bad = [], [], []
    for result in data.get('testResults', []):
        for test in result.get('assertionResults', []):
            name = identity(result['name'], [*test.get('ancestorTitles', []), test['title']])
            status = test.get('status')
            if status == 'skipped' and name in allowed and name not in skipped:
                skipped.append(name)
                continue
            ids.append(name)
            if status != 'passed':
                bad.append(f'{name} [{status}]')
            elif name in allowed:
                bad.append(f'{name} [passed, but required.json pins it as a skipped gap]')
        if result.get('status') not in (None, 'passed') and not result.get('assertionResults'):
            bad.append(f"{result['name']} [{result.get('status')}] {result.get('message', '')[:200]}")
    counts = {k: data.get(k, 0) for k in ('numTotalTests', 'numPassedTests', 'numFailedTests',
                                          'numPendingTests', 'numTodoTests')}
    problems = [f'{config}: {b}' for b in bad[:10]]
    if counts['numFailedTests'] or counts['numTodoTests'] or counts['numPendingTests'] != len(skipped) \
            or counts['numPassedTests'] != len(ids) or counts['numTotalTests'] != len(ids) + len(skipped):
        problems.append(f'{config}: {counts}, {len(skipped)} pinned skips')
    unit = dict(ran=len(ids), passed=counts['numPassedTests'], ran_sum=format(multiset(ids), 'x'),
                skipped=sorted(skipped))
    return unit, problems


def main(shard, total, report, chosen):
    shard, total = int(shard), int(total)
    work = work_dir(f'vitest-{shard}')
    problems, units, listings = [], [], {}
    for index, (config, root, part, parts) in enumerate(plan(total)[shard]):
        if chosen and config not in chosen:
            continue
        common = ['--config', str(ROOT / config), '--root', str(ROOT / root)]
        tag = f'{index}-{part}'
        if part == 1:
            listing = work / f'{tag}.list.json'
            code = run([str(VITEST), 'list', *common, '--json=' + str(listing)], work / f'{tag}.list.log')
            if code != 0 or not listing.is_file():
                problems.append(f'{config}: list exited {code}')
                tail(work / f'{tag}.list.log')
            else:
                ids = [identity(t['file'], t['name'].split(' > ')) for t in json.loads(listing.read_text())]
                listings[config] = dict(listed=len(ids), listed_sum=format(multiset(ids), 'x'),
                                        listed_sha256=hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest())
        output = work / f'{tag}.run.json'
        log = work / f'{tag}.run.log'
        split = [f'--shard={part}/{parts}'] if parts > 1 else []
        print(f'::group::{config} part {part}/{parts}', flush=True)
        code = run([str(VITEST), 'run', *common, *split, '--passWithNoTests', '--reporter=json',
                    '--outputFile=' + str(output)], log)
        unit = dict(config=config, part=part, parts=parts)
        if code != 0 or not output.is_file():
            problems.append(f'{config}: part {part}/{parts} exited {code}')
            tail(log)
        if output.is_file():
            fields, found = judge(config, json.loads(output.read_text()))
            unit.update(fields)
            problems += found
            print(f"{config} part {part}/{parts}: {fields['ran']} ran, {fields['passed']} passed, "
                  f"skipped as pinned {fields['skipped']}")
        print('::endgroup::', flush=True)
        units.append(unit)
    ok = not problems and bool(units)
    return write_report(report, f'shard{shard}', ok, problems, shard=shard, total=total, units=units,
                        listings=listings)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]))
