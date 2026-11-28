import { expect, it } from 'vitest';
import { validateRegistrations } from '../../../../web/registry-loader';
import l16 from '../../../../web/registrations/L16';
import type { Registration } from '../../../../web/registry-types';

const requiredRange = Array.from({ length: 26 }, (_, lane): Registration['lane'] => `L${String(lane).padStart(2, '0')}`);
const rangeReady = requiredRange.every(lane => {
  try { validateRegistrations([{ ...l16, lane }]); return true; } catch { return false; }
});

it.skipIf(!rangeReady).each(requiredRange)(
  'shared-reader prerequisite: admits %s through the production registration validator', lane => {
    const entry = { ...l16, lane };
    expect(validateRegistrations([entry])).toEqual([entry]);
  },
);

it('rejects unsupported lanes and permits absent fragments', () => {
  const invalidLanes = ['L26', 'L99', 'L-1', 'L1', 'L000'] as const satisfies readonly Registration['lane'][];
  for (const lane of invalidLanes) {
    expect(() => validateRegistrations([{ ...l16, lane }])).toThrow();
  }
  expect(validateRegistrations([])).toEqual([]);
});
