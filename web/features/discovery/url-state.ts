import { normalizeDigits } from '@beirut-time/i18n';
export const fields = ['q','brand','model','location','min_minor','max_minor','currency','sale_mode','sort','cursor'] as const;
export type SearchField = typeof fields[number];
export type SearchState = Record<SearchField, string>;
export const defaults: SearchState = { q:'',brand:'',model:'',location:'',min_minor:'',max_minor:'',currency:'USD',sale_mode:'',sort:'newest',cursor:'' };
// CP F-08: one pure URL codec; never copy unknown query parameters into requests.
export function readSearch(params: Pick<URLSearchParams,'get'>): SearchState {
  const state = {...defaults};
  for (const field of fields) {
    const value = params.get(field);
    if (value !== null) state[field] = value.slice(0, field === 'cursor' ? 1024 : 200);
  }
  return state;
}
export function writeSearch(state: SearchState): string {
  const params = new URLSearchParams();
  for (const field of fields) if(state[field] && state[field] !== defaults[field]) params.set(field,state[field]);
  return params.toString();
}
export function searchRangeError(state: SearchState): boolean {
  const min = normalizeDigits(state.min_minor).trim(), max = normalizeDigits(state.max_minor).trim();
  if ([min,max].some(value => value && (!/^\d{1,16}$/.test(value)||BigInt(value)>9000000000000000n))) return true;
  return !!(min && max && BigInt(min) > BigInt(max));
}
export function updateSearch(state: SearchState, patch: Partial<SearchState>): SearchState {
  return { ...state, cursor: '', ...patch };
}
export function saleStateLabel(state: string, t: Record<string,string>): string {
  return state==='not_started'?t.awaitingAuction:state==='unavailable'?t.saleUnavailable:t[state];
}
export function exactMoney(amount: string, currency: string, locale: 'en'|'ar'): string {
  if(!/^-?\d+(\.\d{1,4})?$/.test(amount)) return '—';
  const [whole,fraction=''] = amount.split('.');
  const digits = new Intl.NumberFormat(locale === 'ar' ? 'ar-LB' : 'en-US', {maximumFractionDigits:0}).format(BigInt(whole));
  const decimals = fraction.padEnd(2,'0');
  const decimalDigits = locale === 'ar' ? decimals.replace(/\d/g,d=>'٠١٢٣٤٥٦٧٨٩'[Number(d)]) : decimals;
  return `${digits}${decimals ? (locale === 'ar' ? '٫' : '.')+decimalDigits : ''} ${currency}`;
}
