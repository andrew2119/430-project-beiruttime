type Locale = 'en'|'ar';
type NumberOptions = Omit<Intl.NumberFormatOptions,'numberingSystem'>;
/** Digit shape is a product contract, not an ICU or browser default. */
export function numberFormatter(locale:Locale,options:NumberOptions = {}) {return new Intl.NumberFormat(locale,{...options,numberingSystem:locale === 'ar' ? 'arab' : 'latn'});}
export function formatNumber(value:number|bigint|null|undefined,locale:Locale,options?:NumberOptions,missing = '—'):string {
  if (value == null || typeof value === 'number' && !Number.isFinite(value)) return missing;
  return (options ? numberFormatter(locale,options) : formatters(locale).number).format(value);
}
export type CountWords = Record<Intl.LDMLPluralRule,string>;
const formats = new Map<Locale,{number:Intl.NumberFormat; plural:Intl.PluralRules; decimal:string; digits:string[]}>();
function formatters(locale:Locale) {
  let found = formats.get(locale);
  if (!found) {const number = numberFormatter(locale), integer = numberFormatter(locale,{useGrouping:false});found = {number,plural:new Intl.PluralRules(locale),decimal:number.formatToParts(1.1).find(part=>part.type === 'decimal')?.value ?? '.',digits:Array.from({length:10},(_,digit)=>integer.format(digit))};formats.set(locale,found);}
  return found;
}
export function formatCount(value:number|null|undefined,locale:Locale,words:CountWords,missing:string):string {
  if (value == null || !Number.isSafeInteger(value) || value < 0) return missing;
  const {number,plural} = formatters(locale);return words[plural.select(value)].replaceAll('{count}',number.format(value));
}
/** Decimal strings stay exact, including values beyond safe floating-point
 * precision. The caller supplies currency words and the missing-value label. */
export function formatAmount(value:string|null|undefined,locale:Locale,currency:string,missing:string):string {
  const match = value?.match(/^(\d+)(?:\.(\d{1,2}))?$/);if (!match) return missing;
  const {number,decimal,digits} = formatters(locale), fraction = (match[2] ?? '').padEnd(2,'0').replace(/\d/g,digit=>digits[Number(digit)]);
  return `${number.format(BigInt(match[1]))}${decimal}${fraction} ${currency}`;
}
