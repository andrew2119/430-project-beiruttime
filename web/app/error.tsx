'use client';
import { useLocale } from '@/shell/locale-context';
import { messages } from '@/lib/i18n';
import { State, Button } from '@/shell/primitives';
export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = messages(useLocale());
  return <State kind="error" title={t.errorTitle} body={t.errorBody}><Button chonk onClick={reset}>{t.retry}</Button></State>;
}
