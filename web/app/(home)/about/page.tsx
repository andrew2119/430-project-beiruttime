import { getLocale } from '@/shell/locale';
import { messages } from '@/lib/i18n';
import { ButtonLink, State } from '@/shell/primitives';
export default async function About() {
  const locale=await getLocale(); const t=messages(locale);
  return <State title={t.promiseTitle} body={t.promise1Body}><p>{t.promise2Body}</p><p>{t.promise3Body}</p><ButtonLink href={`/${locale}`}>{t.backHome}</ButtonLink></State>;
}
