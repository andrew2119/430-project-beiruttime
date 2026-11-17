import { formatAmount } from '@beirut-time/ui/foundation';
export function formatMinor(minor: number, currency: 'USD', locale: 'en' | 'ar') {
  if (!Number.isSafeInteger(minor) || minor < 0 || currency !== 'USD') throw new RangeError('Invalid indicative amount');
  return formatAmount(`${Math.floor(minor/100)}.${String(minor%100).padStart(2,'0')}`, locale, 'USD', '—');
}
