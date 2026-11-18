'use client';
import { Button, State } from '@beirut-time/ui/foundation';
import { useLocale } from '@/shell/locale-context';
import { PageBody } from '@/shell/foundation/page';
export default function ErrorPage({reset}: {reset:()=>void}) {
  const ar = useLocale() === 'ar';
  return <PageBody><State kind="error" title={ar ? 'تعذر عرض الصفحة' : 'This page could not be shown'} body={ar ? 'أعد المحاولة لعرض الصفحة.' : 'Try loading this page again.'}><Button variant="outline" onClick={reset}>{ar ? 'أعد المحاولة' : 'Try again'}</Button></State></PageBody>;
}
