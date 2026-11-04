'use client';
import { usePathname, useSearchParams } from 'next/navigation';
import { useState } from 'react';
import type { Locale, Messages } from '@/lib/i18n';
import { Button } from './primitives';
import { localizePath } from './paths';
export function Preferences({ locale, theme, t }: { locale: Locale; theme: 'light' | 'dark'; t: Messages }) {
  const path = usePathname();
  const search = useSearchParams().toString();
  const [current, setCurrent] = useState(theme);
  const other = locale === 'en' ? 'ar' : 'en';
  function toggle() {
    const next = current === 'light' ? 'dark' : 'light';
    document.cookie = `bt-theme=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
    document.documentElement.dataset.theme = next;
    document.documentElement.style.colorScheme = next;
    setCurrent(next);
  }
  return <div className="preferences">
    <a className="locale-control" href={localizePath(path,other) + (search ? `?${search}` : '')} lang={other} hrefLang={other}
      onClick={() => { window.dispatchEvent(new Event('bt:before-locale-change')); document.cookie = `bt-locale=${other}; Path=/; Max-Age=31536000; SameSite=Lax`; }}>
      {other === 'ar' ? 'العربية' : 'English'}
    </a>
    <Button className="icon-button" onClick={toggle} aria-label={current === 'light' ? t.dark : t.light}>
      <span aria-hidden="true">{current === 'light' ? '◐' : '☼'}</span>
    </Button>
  </div>;
}
