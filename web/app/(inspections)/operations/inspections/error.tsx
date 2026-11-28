'use client';

import { Button, ButtonLink, State } from '@beirut-time/ui/foundation';
import { PageBody, PageFrame, PageHeader } from '@/shell/foundation/page';
import { useLocale } from '@/shell/locale-context';
import { copy } from '@/features/private-inspection/copy';

export default function InspectionError({reset}:{reset:()=>void}) {
  const locale = useLocale(), t = copy[locale];
  return <PageFrame><PageHeader title={t.title} lead={t.intro}/><PageBody>
    <State kind="error" title={t.unavailable} body={t.routeUnavailable}>
      <Button onClick={reset}>{t.retry}</Button>
      <ButtonLink href={`/${locale}/account`}>{t.account}</ButtonLink>
    </State>
  </PageBody></PageFrame>;
}
