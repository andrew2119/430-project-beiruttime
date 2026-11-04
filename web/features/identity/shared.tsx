'use client';
import { ApiError } from '@/lib/api/client';
import Link from 'next/link';
import { BidiReference, Button } from '@beirut-time/ui';
import { refreshSession, signInHref, useSessionState } from './session';
import { useLocale } from '@/shell/locale-context';
import en from './en.json';
import ar from './ar.json';
export function useIdentityCopy() { const locale = useLocale(); return { locale, t: locale === 'ar' ? ar : en }; }
export function ErrorNotice({ error }: { error: unknown }) {
  const { t } = useIdentityCopy();
  if (!error) return null;
  const code = error instanceof ApiError ? error.code : 'error';
  const copy = (t as Record<string, string>)[code] ?? (error instanceof ApiError && error.status >= 500 ? t.unavailable : t.error);
  return <div className="identity-feedback" role="alert"><p>{copy}</p>{error instanceof ApiError && error.requestId && <small>{t.reference}: <BidiReference>{error.requestId}</BidiReference></small>}</div>;
}
export function SessionPrompt({ next }: { next: string }) {
  const { t, locale } = useIdentityCopy();
  const state = useSessionState();
  return <div className="identity-stack"><noscript><p className="identity-demo">{t.javascriptRequired}</p></noscript><p role={state === 'unavailable' ? 'alert' : 'status'}>{state === 'restoring' ? t.loading : state === 'unavailable' ? t.unavailable : t.signInRequired}</p>
    {state === 'unavailable' && <Button onClick={()=>void refreshSession().catch(()=>null)}>{t.retry}</Button>}
    {state !== 'restoring' && <Link className="button" href={signInHref(next,locale)}>{t.signin}</Link>}
  </div>;
}
export async function syntheticFile(value: FormDataEntryValue | null) {
  if (!(value instanceof File) || value.size > 65536 || value.size < 5 || !value.name.toLowerCase().endsWith('.txt')) throw new ApiError(422,'badEvidence','');
  const text = await value.text();
  if (!text.startsWith('DEMO:') || new TextEncoder().encode(text).length > 65536) throw new ApiError(422,'badEvidence','');
  return text;
}
