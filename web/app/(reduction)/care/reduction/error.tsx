'use client';

import { Button, ButtonLink, State } from '@beirut-time/ui/foundation';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { copy } from '@/features/reduction/copy';

export default function ReductionError({ reset }: { reset: () => void }) {
  const locale = useLocale(), t = copy[locale];
  return <PageFrame><PageHeader title={t.title} lead={t.measurement}/><PageBody>
    <State kind="error" title={t.unavailable} body={t.unavailableBody}>
      <Button onClick={reset}>{t.refresh}</Button>
      <ButtonLink href={`/${locale}/inbox`} variant="outline">{t.support}</ButtonLink>
    </State>
  </PageBody></PageFrame>;
}
