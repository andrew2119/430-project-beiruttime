'use client';
import { usePageRead } from '@/lib/page-speed/read';
import { definePageRead } from '@/lib/page-speed/definition';
import { Button, ButtonLink } from '@beirut-time/ui/foundation';
import { ApiError } from '@/lib/api/client';
import { useSession, refreshSession, signInHref } from '@/features/identity/session';
import { useLocale } from '@/shell/locale-context';
import en from './en.json';
import ar from './ar.json';

const availabilityRead=definePageRead({key:()=>['directory-session-availability'],warm:'open-only',fresh:0,ask:async()=>Boolean(await refreshSession())});

export function SignInAction({ next, label }: { next: string; label: string }) {
  const locale = useLocale();
  const t = locale === 'ar' ? ar : en;
  const session = useSession();
  const availability = usePageRead(!session ? availabilityRead():null);
  if (session && !session.principal.roles.includes('buyer')) return <p role="alert">{t.buyerRequired}</p>;
  return <>
    {!session && availability.isPending && <p role="status">{t.authPending}</p>}
    {!session && availability.isError && <div className="notice" role="alert">
      <p>{availability.error instanceof ApiError && availability.error.status === 403 ? t.authDenied : t.authUnavailable}</p>
      <Button type="button" variant="outline" onClick={() => void availability.refetch()}>{t.authRetry}</Button>
    </div>}
    <ButtonLink href={signInHref(next, locale)}>{label}</ButtonLink>
  </>;
}
