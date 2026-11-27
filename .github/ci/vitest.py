"""Run one shard of every web Vitest suite and report per suite.

Usage: python .github/ci/vitest.py <shard> <total> <report.json> [config ...]

Each suite runs with Vitest's own --shard=<shard>/<total>.
Each shard also lists a share of the suites unsharded, so the check job can prove that the
shards together ran exactly the listed tests: their counts add up and the order-independent
sums of their test identities match the listed set.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bt_ci import ROOT, write_report, work_dir  # noqa: E402

WEB = ROOT / 'web'
VITEST = WEB / 'node_modules/.bin/vitest'


def configs():
    """Every web suite, in a fixed order: the app, each feature, then the lane suites."""
    found = [('web/vitest.config.ts', 'web')]
    found += [(p.relative_to(ROOT).as_posix(), 'web') for p in sorted((WEB / 'features').glob('*/vitest.config.ts'))]
    found += [('tests/lanes/L04/vitest.config.mts', 'web'), ('tests/lanes/L07/vitest.config.ts', '.'),
              ('tests/lanes/L08/web/vitest.config.ts', '.'), ('tests/lanes/L09/web/vitest.config.ts', 'web')]
    return found


def identity(file, names):
    return Path(file).resolve().relative_to(ROOT).as_posix() + ' > ' + ' > '.join(names)


def multiset(ids):
    """An order-independent sum of test identities that adds up across shards."""
    return sum(int(hashlib.sha256(i.encode()).hexdigest(), 16) for i in ids) % (1 << 256)


def run(command, log):
    with log.open('w') as stream:
        return subprocess.run(command, cwd=WEB, stdout=stream, stderr=subprocess.STDOUT).returncode


def tail(log, lines=40):
    text = log.read_text(errors='replace').splitlines()
    print('\n'.join(text[-lines:]))


def main(shard, total, report, chosen):
    shard, total = int(shard), int(total)
    work = work_dir(f'vitest-{shard}')
    problems, suites = [], {}
    everything = configs()
    for index, (config, root) in enumerate(everything):
        if chosen and config not in chosen:
            continue
        common = ['--config', str(ROOT / config), '--root', str(ROOT / root)]
        entry = {}
        if index % total == shard - 1:
            listing = work / f'{index}.list.json'
            code = run([str(VITEST), 'list', *common, '--json=' + str(listing)], work / f'{index}.list.log')
            if code != 0 or not listing.is_file():
                problems.append(f'{config}: list exited {code}')
                tail(work / f'{index}.list.log')
            else:
                listed = json.loads(listing.read_text())
                ids = [identity(t['file'], t['name'].split(' > ')) for t in listed]
                entry.update(listed=len(ids), listed_sum=format(multiset(ids), 'x'),
                             listed_sha256=hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest())
        output = work / f'{index}.run.json'
        log = work / f'{index}.run.log'
        print(f'::group::{config} shard {shard}/{total}', flush=True)
        code = run([str(VITEST), 'run', *common, f'--shard={shard}/{total}', '--passWithNoTests',
                    '--reporter=json', '--outputFile=' + str(output)], log)
        if code != 0 or not output.is_file():
            problems.append(f'{config}: run exited {code}')
            tail(log)
        if output.is_file():
            data = json.loads(output.read_text())
            ids, bad = [], []
            for result in data.get('testResults', []):
                for test in result.get('assertionResults', []):
                    ids.append(identity(result['name'], [*test.get('ancestorTitles', []), test['title']]))
                    if test.get('status') != 'passed':
                        bad.append(f"{ids[-1]} [{test.get('status')}]")
                if result.get('status') not in (None, 'passed') and not result.get('assertionResults'):
                    bad.append(f"{result['name']} [{result.get('status')}] {result.get('message', '')[:200]}")
            counts = {k: data.get(k, 0) for k in ('numTotalTests', 'numPassedTests', 'numFailedTests',
                                                  'numPendingTests', 'numTodoTests')}
            if counts['numFailedTests'] or counts['numPendingTests'] or counts['numTodoTests'] \
                    or counts['numPassedTests'] != counts['numTotalTests'] or len(ids) != counts['numTotalTests']:
                problems.append(f'{config}: {counts}')
            problems.extend(f'{config}: {b}' for b in bad[:10])
            entry.update(ran=counts['numTotalTests'], passed=counts['numPassedTests'], ran_sum=format(multiset(ids), 'x'))
            print(f'{config}: {counts}')
        print('::endgroup::', flush=True)
        suites[config] = entry
    ok = not problems and bool(suites)
    return write_report(report, f'shard{shard}', ok, problems, shard=shard, total=total, suites=suites)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]))
