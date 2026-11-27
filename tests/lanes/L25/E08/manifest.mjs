import { journeys } from './contract.mjs';
export const scenarios = Object.freeze([
  'positive', 'denied', 'stale', 'cross-account', 'timeout', 'lost-response', 'duplicate',
  'restart', 'offline', 'logout', 'upstream-isolation', 'before-equal-after',
  'keyboard-focus', 'reduced-motion', 'zoom-200', 'private-language-retention',
  'numeric-dollars', 'pagination-1000', 'mixed-content', 'speed-contract',
]);
export const requirements = Object.freeze(journeys.flatMap(journey =>
  ['en', 'ar'].flatMap(language => ['light', 'dark'].flatMap(theme =>
    ['desktop', '390x844', 'physical-phone'].flatMap(device =>
      scenarios.map(scenario => ({ id: [journey, language, theme, device, scenario].join('/'),
        journey, language, theme, device, scenario })))))));
// Only an external completed run can supply results. Missing and skipped rows remain owed.
export function summarize(records = []) {
  const indexed = new Map();
  const known = new Set(requirements.map(row => row.id));
  for (const row of records) {
    if (!known.has(row.id) || indexed.has(row.id)) throw Error('unknown or duplicate result');
    if (!['pass', 'fail', 'skip'].includes(row.result)) throw Error('result');
    if (row.result === 'pass') {
      if (row.source !== 'connected' || !row.reference || !row.observed_at) throw Error('connected reference required');
      const required = requirements.find(item => item.id === row.id);
      if (required.device === '390x844' && (row.innerWidth !== 390 || row.innerHeight !== 844)) throw Error('actual viewport required');
      if (required.device === 'physical-phone' && !row.physical_device) throw Error('physical device required');
    }
    if (row.result === 'skip' && !row.reason) throw Error('skip reason');
    indexed.set(row.id, row);
  }
  return {
    passed: records.filter(row => row.result === 'pass').length,
    failed: records.filter(row => row.result === 'fail').length,
    skipped: records.filter(row => row.result === 'skip').length,
    remaining: requirements.filter(row => indexed.get(row.id)?.result !== 'pass').map(row => row.id),
    complete: requirements.every(row => indexed.get(row.id)?.result === 'pass'),
  };
}
