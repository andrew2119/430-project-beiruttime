import { Suspense } from 'react';
import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import { PageLoading } from '@/shell/foundation/page';
import FitMeasurement from '@/features/fit-measurement/view';
import { copy } from '@/features/fit-measurement/copy';
export async function generateMetadata():Promise<Metadata> {
  return {title:{absolute:(await getLocale())==='ar'?'قياس المعصم والملاءمة المطلوبة · بيروت تايم':'Wrist measurement and target fit · Beirut Time'},robots:{index:false,follow:false}};
}
export default async function Page() {
  const locale=await getLocale();
  return <Suspense fallback={<PageLoading label={copy[locale].loading}/>}><FitMeasurement/></Suspense>;
}

import '@/features/fit-measurement/styles.css';
