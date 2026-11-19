'use client';
import { usePathname } from 'next/navigation';
import { ShellProfile } from './foundation/profile';
import { useLocale } from './locale-context';
import type { Locale } from '@/lib/i18n';
export function ProfileBlock({locale: initialLocale}: {locale:Locale}) {
  const locale = useLocale(initialLocale), path = usePathname();
  return <ShellProfile locale={locale} path={path}/>;
}
