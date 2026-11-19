import { describe, expect, it } from 'vitest';
import { formatUsd, parseUsdInput, usdInputValue, usdPercentage } from '@beirut-time/ui/foundation';

describe('exact dollar input and integer cents', () => {
  it('preserves commercial values across digit shapes and decimal marks', () => {
    for (const text of ['5000', '5000.00', '٥٠٠٠٫٠٠', '۵۰۰۰.۰۰']) {
      expect(parseUsdInput(text)).toEqual({ state: 'valid', currency: 'USD', minor: 500000 });
    }
    expect(parseUsdInput('0.01')).toEqual({ state: 'valid', currency: 'USD', minor: 1 });
    expect(parseUsdInput(' 001.2 ')).toEqual({ state: 'valid', currency: 'USD', minor: 120 });
    expect(parseUsdInput('')).toEqual({ state: 'empty', minor: null });
  });
  it('refuses ambiguous grouping, signs, exponents and extra precision', () => {
    for (const text of ['1,000', '١٬٠٠٠', '1.001', '1.', '.01', '-1', '+1', '1e3', 'NaN', 'Infinity', '$1', '1 USD', '1 00', '1\n2']) {
      expect(parseUsdInput(text)).toEqual({ state: 'invalid', minor: null });
    }
    for (const text of ['90071992547409.92', '9'.repeat(1000)]) expect(parseUsdInput(text).state).toBe('overflow');
  });
  it('round trips the entire safe boundary without binary dollar arithmetic', () => {
    for (const minor of [0, 1, 10, 101, 500000, Number.MAX_SAFE_INTEGER]) {
      expect(parseUsdInput(usdInputValue(minor))).toEqual({ state: 'valid', currency: 'USD', minor });
    }
    expect(usdInputValue(Number.MAX_SAFE_INTEGER)).toBe('90071992547409.91');
    for (const value of [-1, .1, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      expect(() => usdInputValue(value)).toThrow(RangeError);
      expect(formatUsd(value, 'en')).toBe('Unavailable');
      expect(formatUsd(value, 'ar')).toBe('غير متاح');
    }
  });
  it('displays exact cents in both languages, with explicit absent values', () => {
    expect(formatUsd(500001, 'en')).toBe('5,000.01 USD');
    expect(formatUsd(500001, 'ar')).toBe('٥٬٠٠٠٫٠١ دولار أمريكي');
    expect(formatUsd(null, 'en')).toBe('Unavailable');
    expect(formatUsd(undefined, 'ar')).toBe('غير متاح');
  });
  it('rounds percentages half up and preserves the approved fee examples', () => {
    expect(usdPercentage(500000, 300)).toBe(15000);
    expect(usdPercentage(500000, 500)).toBe(25000);
    expect(usdPercentage(10, 500)).toBe(1);
    expect(usdPercentage(9, 500)).toBe(0);
    expect(usdPercentage(Number.MAX_SAFE_INTEGER, 10000)).toBe(Number.MAX_SAFE_INTEGER);
    for (const rate of [-1, .5, NaN, Infinity, 10001]) expect(() => usdPercentage(100, rate)).toThrow(RangeError);
  });
});
