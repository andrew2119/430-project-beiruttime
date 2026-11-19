'use client';
import { Button, State } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { copy } from '@/features/fit-measurement/copy';

export default function FitError({reset}:{reset:()=>void}) {
  const t=copy[useLocale()];
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>
    <State kind="error" title={t.unavailable} body={t.intro}>
      <Button onClick={reset}>{t.reload}</Button>
    </State>
  </PageBody></PageFrame>;
}
