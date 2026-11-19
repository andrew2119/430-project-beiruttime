'use client';

import { ButtonLink, Card } from '@beirut-time/ui/foundation';
import { messages } from '@/lib/i18n';
import { useLocale } from '../locale-context';
import { PageFrame, PageHeader, PageBody } from '@/shell/foundation/page';
import { usePageTitle } from './page-title';
import { AnswerArrival } from '@/lib/page-speed/arrival';

export function AboutPage() {
  const locale = useLocale(), t = messages(locale);
  usePageTitle(t.promiseTitle, locale);
  return <PageFrame><PageHeader title={t.promiseTitle}/><PageBody><AnswerArrival view="about"><Card>
    <p className="bt-text">{t.promise1Body}</p><p className="bt-text">{t.promise2Body}</p><p className="bt-text">{t.promise3Body}</p>
    <ButtonLink prefetch href={`/${locale}`}>{t.backHome}</ButtonLink>
  </Card></AnswerArrival></PageBody></PageFrame>;
}
