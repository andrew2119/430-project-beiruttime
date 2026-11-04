import { headers } from 'next/headers';
import type { Locale } from '@beirut-time/i18n';
export async function getLocale(): Promise<Locale> { return (await headers()).get('x-bt-locale') === 'ar' ? 'ar' : 'en'; }
export async function getPublicPath(): Promise<string> { return (await headers()).get('x-bt-path') ?? '/'; }
