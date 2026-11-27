"""Render the run's executed rows without publishing private proof material."""
import json
from pathlib import Path
import re
import sys

ROWS = {
    'five-services-and-web-ready': 'Five services and Web ready',
    'real-identity-and-catalog-publication': 'Real Identity onboarding and Catalog publication',
    'reserve-private': 'Reserve data stays private',
    'fixed-end-120-90-and-before-zero': 'Fixed end at 120 s, 90 s and just before zero',
    'at-and-after-zero-refused': 'Exact at-/after-zero checks and live late-request refusal',
    'manual-and-two-proxy-rows': 'Manual bid and two proxy rows',
    'removed-controls-unavailable': 'Removed controls and purchase commands unavailable',
    'historical-order-read-actor-scoped': 'Actor-scoped historical Order read',
    'browser-en-ar-dark-light-390': 'Real browser recovery and EN/AR × light/dark × 390 px',
}
HISTORICAL = 'historical-order-read-actor-scoped'
HISTORICAL_REASON = ('This Batch 7 base has no historical Order lookup on the Auction service '
                     'and no approved retained pre-bid Order fixture.')
APPS = {'identity', 'catalog', 'auction', 'pricing', 'orders', 'web'}
PHASES = ('build', 'packaged', 'stack', 'publication', 'policy-auction', 'policy', 'browser-matrix',
          'browser-screens', 'race', 'fixed', 'late', 'close', 'historical')
STATES = ('pass', 'fail', 'not-run')
LATE_ROW = 'at-and-after-zero-refused'


def receipt(path, sha):
    try:
        value = json.loads(path.read_text())
        if type(value) is not dict or value.get('sha') != sha or type(value.get('complete')) is not bool:
            return None
        rows, phases = value.get('rows'), value.get('phases')
        if (type(rows) is not dict or set(rows) != set(ROWS) or any(state not in STATES for state in rows.values())
                or type(phases) is not dict or set(phases) != set(PHASES)
                or any(state not in STATES for state in phases.values())
                or type(value.get('cleanup_incomplete')) is not list
                or (rows[LATE_ROW] == 'pass' and value.get('late_guard') not in ('refusal-only', 'deadline-specific'))):
            return None
        if 'pass' in rows.values():
            images = value.get('images')
            if (type(images) is not dict or set(images) != APPS or not all(
                    isinstance(i, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', i) for i in images.values())):
                return None
        return value
    except (OSError, ValueError):
        return None


def render(value, sha):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Missing or invalid checked-out SHA')
    states = value['rows'] if value is not None else dict.fromkeys(ROWS, 'not-run')
    good = {row for row, state in states.items() if state == 'pass'}
    display = {'pass': '**PASS**', 'fail': '**FAIL**', 'not-run': '**NOT RUN**'}
    lines = ['## L12 image proof — diagnostic', '', f'Checked-out SHA: `{sha}`', '',
             '| Required row | Observed result |', '| --- | --- |']
    for key, label in ROWS.items():
        result = display[states[key]]
        if key == HISTORICAL and key not in good:
            result += f' — **RED** on this base. {HISTORICAL_REASON}'
        if key == LATE_ROW and key in good and value['late_guard'] == 'refusal-only':
            result += ' — deadline-specific live admission guard unproved; this is only a late-request refusal.'
        lines.append(f'| {label} | {result} |')
    if value is None:
        lines += ['', 'No valid receipt for this SHA; no row was credited.']
    else:
        failed = [phase for phase in PHASES if value['phases'][phase] == 'fail']
        if failed:
            lines += ['', 'Failed phases: ' + ', '.join(f'`{phase}`' for phase in failed) + '.']
        if value['cleanup_incomplete']:
            lines += ['', '**Cleanup incomplete.** Unconfirmed or changed objects were not removed by a broader selector.']
    if good & {'fixed-end-120-90-and-before-zero', LATE_ROW}:
        lines += ['', 'Exact ±1 ms and zero offsets use the packaged Auction code, not an exactly timed HTTP mutation.']
    if value is None or not value['complete']:
        lines += ['', 'This diagnostic is not a green L12 proof.']
    return '\n'.join(lines)


if __name__ == '__main__':
    path, commit = sys.argv[1:]
    print(render(receipt(Path(path), commit), commit))
