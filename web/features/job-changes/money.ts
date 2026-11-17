/** Format retained USD cents without rounding through a fractional number. */
export function formatUsdMinor(minor: number, locale: 'en' | 'ar'): string {
  if (!Number.isSafeInteger(minor) || minor < 0) throw new RangeError('invalid_money');
  const cents = BigInt(minor);
  const fraction = new Intl.NumberFormat(locale, {
    minimumIntegerDigits: 2, useGrouping: false,
  }).format(Number(cents % 100n));
  return new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD' })
    .formatToParts(cents / 100n)
    .map(part => part.type === 'fraction' ? fraction : part.value)
    .join('');
}
