import type { Metadata } from 'next';
import Cleaning from '@/features/cleaning/view';
import { getLocale } from '@/shell/locale';
export async function generateMetadata():Promise<Metadata> {
  const locale=await getLocale();
  return {title:{absolute:locale==='ar'?'طلب تنظيف خارجي · بيروت تايم':'Request external cleaning · Beirut Time'},robots:{index:false,follow:false}};
}
export default function CleaningPage() {
  return <Cleaning/>;
}
