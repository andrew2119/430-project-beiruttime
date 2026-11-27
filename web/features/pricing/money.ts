import { normalizeDigits, type Locale } from '@beirut-time/i18n';
import type { Currency } from '@contracts/contracts-pricing/quotes';
const MAX = 9_000_000_000_000n;
export function parseMinor(input:string, currency:Currency):number {
  if(currency!=='USD') throw new Error('invalidMoney');
  const text=normalizeDigits(input).trim();
  if(!/^\d+(?:\.\d{1,2})?$/.test(text) || text.length>20) throw new Error('invalidMoney');
  const [whole,fraction='']=text.split('.');
  const scale=100n;
  const value=BigInt(whole)*scale+BigInt(fraction.padEnd(2,'0'));
  if(value<=0n || value>MAX) throw new Error('invalidMoney');
  return Number(value);
}
export function money(minor:number,currency:Currency,locale:Locale):string {
  if(currency!=='USD'||!Number.isSafeInteger(minor)||minor<0) throw new Error('Invalid USD cents');
  const scale=100n, amount=BigInt(minor);
  const fmt=new Intl.NumberFormat(locale==='ar'?'ar-LB':'en-US');
  const whole=fmt.format(amount/scale);
  const fraction=scale===100n?(locale==='ar'?'٫':'.')+new Intl.NumberFormat(locale==='ar'?'ar-LB':'en-US',{minimumIntegerDigits:2,useGrouping:false}).format(amount%100n):'';
  return `${whole}${fraction} ${currency}`;
}
export function editableAmount(minor:number,currency:Currency) { if(currency!=='USD'||!Number.isSafeInteger(minor)||minor<0)throw new Error('invalidMoney');const scale=100;return `${Math.trunc(minor/scale)}.${String(minor%scale).padStart(2,'0')}`; }
export const validReference=(value:string)=>/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
export function parseRevision(value:string) { const text=normalizeDigits(value); if(!/^[1-9]\d{0,8}$/.test(text)) throw new Error('invalidReference'); return Number(text); }
