import { Suspense } from 'react';
import { getLocale } from '@/shell/locale';
import { PageLoading } from '@/shell/foundation/page';
import TransactionEmailPage from './page';
export async function generateMetadata() {
  return {title: (await getLocale()) === 'ar' ? 'البريد الإلكتروني للمعاملات · بيروت تايم' : 'Transactional email · Beirut Time', robots:{index:false,follow:false}};
}
export default async function Page() {
  const locale = await getLocale();
  return <Suspense fallback={<PageLoading label={locale==='ar'?'جارٍ تحميل السجلات الخاصة':'Loading private records'}/>}><TransactionEmailPage/></Suspense>;
}
