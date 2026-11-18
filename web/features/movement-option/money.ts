export function formatMinor(minor: number, currency: 'USD' | 'LBP', locale: 'en' | 'ar', minorUnits = 'minor units') {
  if (!Number.isSafeInteger(minor) || minor < 0 || (currency !== 'USD' && currency !== 'LBP')) throw new RangeError('Invalid indicative amount');
  if (currency === 'LBP') return `${new Intl.NumberFormat(`${locale}-LB`).format(minor)} LBP · ${minorUnits}`;
  const options = { numberingSystem: locale === 'ar' ? 'arab' : 'latn' };
  const number = new Intl.NumberFormat(locale, options);
  const integer = new Intl.NumberFormat(locale, { ...options, useGrouping: false });
  const decimal = number.formatToParts(1.1).find(part => part.type === 'decimal')?.value ?? '.';
  const fraction = String(minor % 100).padStart(2, '0').replace(/\d/g, digit => integer.format(Number(digit)));
  return `${number.format(BigInt(Math.floor(minor / 100)))}${decimal}${fraction} USD`;
}
