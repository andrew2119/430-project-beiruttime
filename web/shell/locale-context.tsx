'use client';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { useRouter } from 'next/navigation';
import { localizePath } from './paths';
import { captureLocaleLink } from './locale-change';
import type { Locale } from '@beirut-time/i18n';
export const LocaleContext = createContext<Locale | null>(null);
export const useLocale = (fallback: Locale = 'en') => useContext(LocaleContext) ?? fallback;

export const LocaleActionsContext = createContext<(locale: Locale) => void>(() => {});
export const useLocaleChange = () => useContext(LocaleActionsContext);
export const useChangeLocale = useLocaleChange;

/** Only the language preference is durable; the mounted page owns its drafts. */
export function LocaleProvider({ locale, children }: { locale: Locale; children: ReactNode }) {
  const [current, setCurrent] = useState(locale);
  const router = useRouter();
  useEffect(() => {
    const restore = () => {
      const prefix = new URL(window.location.href).pathname.split('/')[1];
      if (prefix !== 'en' && prefix !== 'ar') return;
      document.documentElement.lang = prefix;
      document.documentElement.dir = prefix === 'ar' ? 'rtl' : 'ltr';
      document.cookie = `bt-locale=${prefix}; Path=/; Max-Age=31536000; SameSite=Lax`;
      setCurrent(prefix);
    };
    window.addEventListener('popstate', restore);
    return () => window.removeEventListener('popstate', restore);
  }, []);
  const change = (next: Locale) => {
    if (next === current) return;
    const url = new URL(window.location.href);
    url.pathname = localizePath(url.pathname, next);
    document.cookie = `bt-locale=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
    // External history updates must synchronize the route before its refresh.
    const retainedState = {...window.history.state};
    delete retainedState.__NA;
    delete retainedState._N;
    window.history.replaceState(retainedState, '', url);
    document.documentElement.lang = next;
    document.documentElement.dir = next === 'ar' ? 'rtl' : 'ltr';
    setCurrent(next);
    // Merge fresh server copy and locale props into the mounted client tree.
    router.refresh();
  };
  useEffect(() => {
    const click = (event: MouseEvent) => captureLocaleLink(event, change);
    window.addEventListener('click', click, true);
    return () => window.removeEventListener('click', click, true);
  });
  return <LocaleContext value={current}><LocaleActionsContext value={change}>{children}</LocaleActionsContext></LocaleContext>;
}
