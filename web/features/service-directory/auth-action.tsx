'use client';
import { useQuery } from '@tanstack/react-query';
import { Button, ButtonLink } from '@beirut-time/ui';
import { ApiError } from '@/lib/api/client';
import { useSession, refreshSession, signInHref } from '@/features/identity/session';
import { useLocale } from '@/shell/locale-context';
import en from './en.json';
import ar from './ar.json';

export function SignInAction({ next, label }: { next: string; label: string }) {
  const locale = useLocale();
  const t = locale === 'ar' ? ar : en;
  const session = useSession();
  const availability = useQuery({
    queryKey: ['service-directory-session-availability'],
    // Credentials stay exclusively in Identity's session module, never in a query cache.
    queryFn: async () => Boolean(await refreshSession()),
    enabled: !session,
    staleTime: Infinity,
    retry: false,
    retryOnMount: false,
    refetchOnReconnect: false,
  });
  if (session && !session.principal.roles.includes('buyer')) return <p role="alert">{t.buyerRequired}</p>;
  return <>
    {!session && availability.isPending && <p role="status">{t.authPending}</p>}
    {!session && availability.isError && <div className="notice" role="alert">
      <p>{availability.error instanceof ApiError && availability.error.status === 403 ? t.authDenied : t.authUnavailable}</p>
      <Button type="button" className="button-secondary" onClick={() => void availability.refetch()}>{t.authRetry}</Button>
    </div>}
    <ButtonLink href={signInHref(next, locale)}>{label}</ButtonLink>
  </>;
}
