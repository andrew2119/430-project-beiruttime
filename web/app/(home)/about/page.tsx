import { getLocale } from '@/shell/locale';
import { messages } from '@/lib/i18n';
import { State } from '@beirut-time/ui';
import { ButtonLink } from '@beirut-time/ui';
import { PageLayout } from '@/shell/page-header';
export default async function About() {
  const locale=await getLocale(); const t=messages(locale);
  return <PageLayout><State title={t.promiseTitle} body={t.promise1Body}><p className="pg-face-copy">{t.promise2Body}</p><p className="pg-face-copy">{t.promise3Body}</p><ButtonLink size="sm" href={`/${locale}`}>{t.backHome}</ButtonLink></State></PageLayout>;
}
