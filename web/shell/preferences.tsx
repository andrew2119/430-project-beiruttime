'use client';
import { usePathname, useSearchParams } from 'next/navigation';
import { Moon, Sun } from 'lucide-react';
import { useTheme } from './theme-provider';
import type { Locale, Messages } from '@/lib/i18n';
import { Button } from './primitives';
import { localizePath } from './paths';
export function Preferences({ locale, theme, t }: { locale: Locale; theme: 'light' | 'dark'; t: Messages }) {
  const path = usePathname();
  const search = useSearchParams().toString();
  const { theme: current, cycleTheme } = useTheme();
  void theme;
  const other = locale === 'en' ? 'ar' : 'en';
  return <div className="preferences">
    <a className="locale-control" href={localizePath(path,other) + (search ? `?${search}` : '')} lang={other} hrefLang={other}
      onClick={() => { window.dispatchEvent(new Event('bt:before-locale-change')); document.cookie = `bt-locale=${other}; Path=/; Max-Age=31536000; SameSite=Lax`; }}>
      {other === 'ar' ? 'العربية' : 'English'}
    </a>
    <Button variant="ghost" size="icon" className="icon-button" onClick={cycleTheme} aria-label={current === 'light' ? t.dark : t.light}>
      {current === 'light' ? <Moon aria-hidden="true"/> : <Sun aria-hidden="true"/>}
    </Button>
  </div>;
}
