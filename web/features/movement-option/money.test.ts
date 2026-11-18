import { describe, expect, it } from 'vitest';
import { formatAmount } from '../../../packages/ui/src/foundation/numbers';
import { formatMinor } from './money';

describe('indicative dollar amounts', () => {
  for (const locale of ['en', 'ar'] as const) {
    it(`matches shared exact formatting in ${locale}`, () => {
      for (const minor of [0, 1, 99, 100, 25000, 123456789, Number.MAX_SAFE_INTEGER]) {
        const decimal = `${Math.floor(minor / 100)}.${String(minor % 100).padStart(2, '0')}`;
        expect(formatMinor(minor, 'USD', locale)).toBe(formatAmount(decimal, locale, 'USD', '—'));
      }
    });
  }
  it('uses Arabic digits', () => {
    expect(formatMinor(12345, 'USD', 'ar')).toBe('١٢٣٫٤٥ USD');
  });
  it('keeps raw minor units and the supplied label for legacy amounts', () => {
    for (const locale of ['en', 'ar'] as const) {
      const label = locale === 'ar' ? 'وحدات صغرى' : 'minor units';
      expect(formatMinor(25000000, 'LBP', locale, label)).toBe(
        `${new Intl.NumberFormat(`${locale}-LB`).format(25000000)} LBP · ${label}`,
      );
    }
  });
  it('rejects invalid amounts and unsupported currencies', () => {
    for (const minor of [Infinity, NaN, -1, 0.5, Number.MAX_SAFE_INTEGER + 1]) {
      expect(() => formatMinor(minor, 'USD', 'en')).toThrow(RangeError);
    }
    expect(() => formatMinor(100, 'EUR' as 'USD', 'en')).toThrow(RangeError);
  });
});
