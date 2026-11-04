import type { Locale } from '@/lib/i18n';
export function stripLocale(path: string) { return path.replace(/^\/(en|ar)(?=\/|$)/,'') || '/'; }
export function localizePath(path: string, locale: Locale) { const clean=stripLocale(path); return `/${locale}${clean==='/'?'':clean}`; }
