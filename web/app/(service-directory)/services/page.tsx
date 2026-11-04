import { Suspense } from 'react';
import { Skeleton } from '@beirut-time/ui';
import ServiceDirectory from '@/features/service-directory/view';
import { getLocale } from '@/shell/locale';
export default async function ServicesPage() {
  const locale = await getLocale();
  return <Suspense fallback={<Skeleton label={locale==='ar'?'جارٍ تحميل الدليل…':'Loading the directory…'}/>}><ServiceDirectory/></Suspense>;
}
