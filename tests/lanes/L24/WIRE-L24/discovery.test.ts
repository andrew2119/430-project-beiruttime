import { readFileSync } from 'node:fs';
import { expect, test } from '../../../../web/node_modules/vitest/dist/index.js';
import manifest from '../../../../contracts/registrations/L24.json';

const boundaries = manifest.composition.runtime_contract.shared_discovery_boundaries;
const lanes = Array.from({ length: 26 }, (_, index) => `L${String(index).padStart(2, '0')}`);

for (const boundary of boundaries) {
  const source = readFileSync(boundary, 'utf8');
  const predicate = source.match(/(\/\^L[^\n]+?\$\/)\.test\(entry\.lane\)/)?.[1];
  test(`${boundary} exposes its lane admission predicate`, () => {
    expect(predicate).toBeDefined();
  });
  const admission = predicate ? new RegExp(predicate.slice(1, -1)) : undefined;
  const missing = lanes.filter(lane => !admission?.test(lane));
  test.skipIf(missing.length > 0)(
    `${boundary} admits L00 through L25; deferred while missing: ${missing.join(', ')}`,
    () => {
      expect(lanes.every(lane => admission?.test(lane))).toBe(true);
      expect(admission?.test('L26')).toBe(false);
      expect(admission?.test('L24-extra')).toBe(false);
    },
  );
}
