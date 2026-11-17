import { expect, it } from 'vitest';
import { formatUsdMinor } from './money';

it('displays exact retained cents across the supported range in both languages', () => {
  const cases: [number, string, string][] = [
    [0, '0.00', '٠٫٠٠'],
    [1, '0.01', '٠٫٠١'],
    [99, '0.99', '٠٫٩٩'],
    [100, '1.00', '١٫٠٠'],
    [101, '1.01', '١٫٠١'],
    [500000, '5,000.00', '٥٬٠٠٠٫٠٠'],
    [9007199254740990, '90,071,992,547,409.90', '٩٠٬٠٧١٬٩٩٢٬٥٤٧٬٤٠٩٫٩٠'],
    [9007199254740991, '90,071,992,547,409.91', '٩٠٬٠٧١٬٩٩٢٬٥٤٧٬٤٠٩٫٩١'],
  ];
  for (const [minor, en, ar] of cases) {
    expect(formatUsdMinor(minor, 'en')).toBe(`$${en}`);
    const arabicDigits = new Intl.NumberFormat('ar').resolvedOptions().numberingSystem === 'arab';
    expect(formatUsdMinor(minor, 'ar')).toBe(`\u200f${arabicDigits ? ar : en}\u00a0US$`);
  }
});

it('rejects amounts outside the supported integer range', () => {
  for (const minor of [-1, 0.5, Infinity, NaN, 9007199254740992]) {
    expect(() => formatUsdMinor(minor, 'en')).toThrow('invalid_money');
  }
});
