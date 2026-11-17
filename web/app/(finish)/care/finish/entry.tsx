import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import { Suspense } from 'react';
import Finish from '@/features/finish/view';
export async function generateMetadata():Promise<Metadata> {
  return {title:{absolute:(await getLocale())==='ar'?'الموافقة على التشطيب · بيروت تايم':'Finish consent · Beirut Time'},robots:{index:false,follow:false}};
}
export default function FinishPage() {
  return <Suspense fallback={null}><Finish/></Suspense>;
}
