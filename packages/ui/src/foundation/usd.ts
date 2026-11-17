import { formatAmount } from './numbers';

type Locale = 'en' | 'ar';
export type DollarInput =
  | { state: 'valid'; currency: 'USD'; minor: number }
  | { state: 'empty' | 'invalid' | 'overflow'; minor: null };
const MAX_MINOR = BigInt(Number.MAX_SAFE_INTEGER);

/** Dollar text is never parsed through floating point or silently rounded.
 * Grouping and currency decorations belong to display, never editable values. */
export function parseUsdInput(text: string): DollarInput {
  const value = text.trim().replace(/[٠-٩۰-۹]/g, digit => {
    const code = digit.charCodeAt(0);
    return String(code >= 0x6f0 ? code - 0x6f0 : code - 0x660);
  }).replaceAll('٫', '.');
  if (!value) return { state: 'empty', minor: null };
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(value);
  if (!match) return { state: 'invalid', minor: null };
  // Bound conversion before constructing a potentially very large integer.
  const whole = match[1].replace(/^0+/, '') || '0';
  if (whole.length > 14) return { state: 'overflow', minor: null };
  const minor = BigInt(whole) * 100n + BigInt((match[2] ?? '').padEnd(2, '0'));
  if (minor > MAX_MINOR) return { state: 'overflow', minor: null };
  return { state: 'valid', currency: 'USD', minor: Number(minor) };
}

/** Exact editable dollars, without grouping, sign or a currency symbol. */
export function usdInputValue(minor: number): string {
  if (!Number.isSafeInteger(minor) || minor < 0) throw new RangeError('Invalid USD cents');
  const value = BigInt(minor);
  return `${value / 100n}.${String(value % 100n).padStart(2, '0')}`;
}

export function formatUsd(minor: number | null | undefined, locale: Locale): string {
  const missing = locale === 'ar' ? 'غير متاح' : 'Unavailable';
  if (minor == null || !Number.isSafeInteger(minor) || minor < 0) return missing;
  return formatAmount(usdInputValue(minor), locale, locale === 'ar' ? 'دولار أمريكي' : 'USD', missing);
}

/** Nonnegative percentage basis points, rounded half up to one cent. */
export function usdPercentage(minor: number, basisPoints: number): number {
  usdInputValue(minor);
  if (!Number.isSafeInteger(basisPoints) || basisPoints < 0 || basisPoints > 10000) throw new RangeError('Invalid percentage');
  return Number((BigInt(minor) * BigInt(basisPoints) + 5000n) / 10000n);
}
