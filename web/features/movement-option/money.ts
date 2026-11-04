// LBP exponent/rounding requires the versioned pricing policy; never guess a major-unit amount.
export function formatMinor(minor: number, currency: 'USD' | 'LBP', locale: 'en' | 'ar', minorLabel: string) {
  if (!Number.isSafeInteger(minor) || minor < 0 || !['USD', 'LBP'].includes(currency)) {
    throw new RangeError('Invalid indicative amount');
  }
  const language = locale === 'ar' ? 'ar-LB' : 'en-LB';
  if (currency === 'LBP') {
    return `${new Intl.NumberFormat(language, { maximumFractionDigits: 0 }).format(minor)} LBP · ${minorLabel}`;
  }
  return new Intl.NumberFormat(language, {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(minor / 100);
}
