import { normalizeDigits } from '@beirut-time/i18n';
export const fields = ['q','brand','model','location','min_price','max_price','currency','sale_mode','sort','cursor'] as const;
export type SearchField = typeof fields[number];
export type SearchState = Record<SearchField, string>;
export const defaults: SearchState = { q:'',brand:'',model:'',location:'',min_price:'',max_price:'',currency:'USD',sale_mode:'',sort:'newest',cursor:'' };
// One pure URL codec; never copy unknown query parameters into requests.
export function readSearch(params: Pick<URLSearchParams,'get'>): SearchState {
  const state = {...defaults};
  for (const field of fields) {
    const value = params.get(field);
    if (value !== null) state[field] = value.slice(0, field === 'cursor' ? 1024 : 200);
  }
  for (const [legacy, field] of [['min_minor','min_price'],['max_minor','max_price']] as const) {
    const value=params.get(legacy);
    if(value!==null && params.get(field)===null) {
      const digits=normalizeDigits(value).trim();
      state[field]=/^\d{1,16}$/.test(digits)?`${BigInt(digits)/100n}.${String(BigInt(digits)%100n).padStart(2,'0')}`:'invalid';
    }
  }
  return state;
}
export function writeSearch(state: SearchState): string {
  const params = new URLSearchParams();
  for (const field of fields) if(state[field] && state[field] !== defaults[field]) params.set(field,state[field]);
  return params.toString();
}
export function dollarsToMinor(value: string): string | null {
  const normalized = normalizeDigits(value).trim().replace('٫','.');
  if (!normalized) return '';
  if (!/^\d{1,14}(?:\.\d{1,2})?$/.test(normalized)) return null;
  const [whole, fraction = ''] = normalized.split('.');
  const minor = BigInt(whole) * 100n + BigInt(fraction.padEnd(2,'0'));
  return minor <= 9000000000000000n ? String(minor) : null;
}
export function searchRangeError(state: SearchState): boolean {
  const min = dollarsToMinor(state.min_price), max = dollarsToMinor(state.max_price);
  return state.currency !== 'USD' || min === null || max === null || !!(min && max && BigInt(min) > BigInt(max));
}
export function requestSearch(state: SearchState): string {
  if (searchRangeError(state)) throw new RangeError('Invalid dollar range');
  const params = new URLSearchParams(writeSearch(state));
  params.delete('min_price'); params.delete('max_price');
  for (const [field, value] of [['min_minor',state.min_price],['max_minor',state.max_price]]) {
    const minor = dollarsToMinor(value);
    if (minor) params.set(field, minor);
  }
  return params.toString();
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
