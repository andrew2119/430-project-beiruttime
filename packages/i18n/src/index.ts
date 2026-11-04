import en from '../messages/en.json';
import ar from '../messages/ar.json';
export const locales = ['en','ar'] as const;
export type Locale = typeof locales[number];
export type Messages = typeof en;
export const isLocale = (value: string): value is Locale => locales.includes(value as Locale);
export const messages = (locale: Locale): Messages => locale === 'ar' ? ar : en;
export const direction = (locale: Locale) => locale === 'ar' ? 'rtl' : 'ltr';
/** Normalize Eastern Arabic/Persian input without changing exact decimal semantics. */
export function normalizeDigits(value: string): string {
  return value.replace(/[٠-٩]/g,c => String(c.charCodeAt(0)-0x660)).replace(/[۰-۹]/g,c => String(c.charCodeAt(0)-0x6f0)).replace(/٫/g,'.').replace(/٬/g,',');
}
