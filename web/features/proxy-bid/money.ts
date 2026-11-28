import { formatAmount } from '@beirut-time/ui/foundation';
import { normalizeDigits, type Locale } from '@beirut-time/i18n';
export function parseMaximum(value:string):number|null {
  const normalized=normalizeDigits(value.trim());
  // Ambiguous grouping and exponent notation must never change a private cap.
  if(!/^\d{1,14}(\.\d{1,2})?$/.test(normalized)) return null;
  const [major,fraction='']=normalized.split('.');
  const minor=BigInt(major)*100n+BigInt(fraction.padEnd(2,'0'));
  return minor>0n&&minor<=9_000_000_000_000_000n?Number(minor):null;
}
export function formatMinor(minor:number,currency:'USD'|'LBP',locale:Locale):string {
  if(!Number.isSafeInteger(minor)||minor<0) return '—';
  const amount=BigInt(minor);
  const dollars=`${amount/100n}.${(amount%100n).toString().padStart(2,'0')}`;
  return formatAmount(dollars,locale,currency,'—');
}
