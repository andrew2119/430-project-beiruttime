'use client';
import { useEffect, useState } from 'react';
import type { Locale } from '@beirut-time/i18n';
import { LocaleContext } from './locale-context';
import { DirectionProvider } from '@beirut-time/ui';
import { InstallPromptProvider } from './install-prompt-provider';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ApiError } from '@/lib/api/client';
// No private cache persistence. Identity must clear this cache on principal changes.
export function Providers({ children, locale }: { children: React.ReactNode; locale: Locale }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: {
    staleTime: 30000, refetchOnWindowFocus: false,
    retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status < 500),
  } } }));
  useEffect(() => {
    const purge = () => { void client.cancelQueries().catch(() => {}); client.clear(); };
    window.addEventListener('bt:access-change', purge);
    return () => window.removeEventListener('bt:access-change', purge);
  }, [client]);
  return <LocaleContext value={locale}><DirectionProvider dir={locale==='ar'?'rtl':'ltr'}><QueryClientProvider client={client}><InstallPromptProvider>{children}</InstallPromptProvider></QueryClientProvider></DirectionProvider></LocaleContext>;
}
