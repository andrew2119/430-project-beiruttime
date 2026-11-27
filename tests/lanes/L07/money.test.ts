import { expect, test } from '../../../web/node_modules/vitest/dist/index.js';
import type { Currency } from '../../../packages/contracts-pricing/quotes';
import { parseMinor, money, editableAmount, parseRevision } from '../../../web/features/pricing/money';

test.each([
  ['5000', 500000],
  ['٥٠٠٠٫٠٠', 500000],
  ['۵۰۰۰.۰۰', 500000],
  ['٢٥٠٫٠١', 25001],
  ['۲۵۰٫۰۱', 25001],
  [' ١٫٠ ', 100],
  ['0.01', 1],
  ['٠٫٠١', 1],
  ['90000000000.00', 9000000000000],
  ['٩٠٠٠٠٠٠٠٠٠٠٫٠٠', 9000000000000],
])('parses exact USD input %s', (input: string, expected: number) => {
  expect(parseMinor(input, 'USD')).toBe(expected);
});

test.each([
  '5,000', '٥٬٠٠٠', '5,000.00', '٥٬٠٠٠٫٠٠', '1,00', '1.2٫3',
  '5e3', 'NaN', 'Infinity', '1.001', '١٫٠٠١', '-1', '+1', '0', '٠٫٠٠',
  '90000000000.01', '٩٠٠٠٠٠٠٠٠٠٠٫٠١', '90071992547409.92',
  '', ' ', '.01', '1.', '1 000', '1 USD',
])('rejects ambiguous, inexact or out-of-range USD input %s', (input: string) => {
  expect(() => parseMinor(input, 'USD')).toThrow('invalidMoney');
});

test('exact USD display and editable values retain cents', () => {
  expect(money(515000, 'USD', 'en')).toBe('5,150.00 USD');
  expect(money(1, 'USD', 'en')).toBe('0.01 USD');
  expect(money(9000000000000, 'USD', 'en')).toBe('90,000,000,000.00 USD');
  expect(money(25001, 'USD', 'ar')).toBe('٢٥٠٫٠١ USD');
  expect(editableAmount(101, 'USD')).toBe('1.01');
  expect(editableAmount(1, 'USD')).toBe('0.01');
  expect(editableAmount(9000000000000, 'USD')).toBe('90000000000.00');
  for (const minor of [1, 101, 25001, 9000000000000]) {
    expect(parseMinor(editableAmount(minor, 'USD'), 'USD')).toBe(minor);
  }
});

test('rejects unsupported currency at runtime', () => {
  const currency = 'unsupported' as Currency;
  expect(() => parseMinor('1.00', currency)).toThrow('invalidMoney');
  expect(() => money(100, currency, 'en')).toThrow('Invalid USD cents');
  expect(() => editableAmount(100, currency)).toThrow('invalidMoney');
});

test('revisions accept localized whole digits only', () => {
  expect(parseRevision('٢')).toBe(2);
  expect(() => parseRevision('1.0')).toThrow();
});
