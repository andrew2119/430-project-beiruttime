import { headers } from 'next/headers';
import { messages } from '@/lib/i18n';
import { State, ButtonLink } from '@/shell/primitives';
export default async function NotFound() { const locale = (await headers()).get('x-bt-locale') === 'ar' ? 'ar' : 'en'; const t = messages(locale); return <State title={t.notFound} body=""><ButtonLink chonk href={`/${locale}`}>{t.backHome}</ButtonLink></State>; }
