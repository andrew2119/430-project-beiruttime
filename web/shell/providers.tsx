'use client';
import { useCallback, useEffect, useState } from 'react';
import type { Locale } from '@beirut-time/i18n';
import { LocaleContext, LocaleActionsContext } from './locale-context';
import { applyLocale,captureLocaleLink } from './locale-change';
import { DirectionProvider } from '@beirut-time/ui';
import { InstallPromptProvider } from './install-prompt-provider';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
// Identity changes clear private query data. Locale changes keep the same live tree.
export function Providers({ children, locale }: { children: React.ReactNode; locale: Locale }) {
  const [currentLocale,setCurrentLocale]=useState(locale);
  const changeLocale=useCallback((next:Locale)=>{applyLocale(next);setCurrentLocale(next);},[]);
  useEffect(()=>{
    // Window capture precedes old per-form navigation handlers; no save is needed.
    const click=(event:MouseEvent)=>captureLocaleLink(event,changeLocale);
    const pop=()=>{const next=/^\/(en|ar)(?:\/|$)/.exec(window.location.pathname)?.[1];if(next==='en'||next==='ar')changeLocale(next);};
    window.addEventListener('click',click,true);window.addEventListener('popstate',pop);
    return()=>{window.removeEventListener('click',click,true);window.removeEventListener('popstate',pop);};
  },[changeLocale]);
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: {
    staleTime: 30000, refetchOnWindowFocus: false,
    retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status < 500),
  } } }));
  useEffect(() => {
    const purge = () => { void client.cancelQueries().catch(() => {}); client.clear(); };
    window.addEventListener('bt:access-change', purge);
    return () => window.removeEventListener('bt:access-change', purge);
  }, [client]);
  return <LocaleActionsContext value={changeLocale}><LocaleContext value={currentLocale}><DirectionProvider dir={currentLocale==='ar'?'rtl':'ltr'}><QueryClientProvider client={client}><InstallPromptProvider>{children}</InstallPromptProvider></QueryClientProvider></DirectionProvider></LocaleContext></LocaleActionsContext>;
}
