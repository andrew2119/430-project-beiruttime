import { formatAmount } from '@beirut-time/ui/foundation';
export function money(minor: number, locale: 'en' | 'ar') {
  if (!Number.isSafeInteger(minor) || minor < 0) return locale === 'ar' ? 'غير متاح' : 'Unavailable';
  const cents = BigInt(minor);
  const decimal = `${cents / 100n}.${String(cents % 100n).padStart(2, '0')}`;
  return formatAmount(decimal, locale, locale === 'ar' ? 'دولار أمريكي' : 'USD', locale === 'ar' ? 'غير متاح' : 'Unavailable');
}
