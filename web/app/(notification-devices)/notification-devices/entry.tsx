import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
export async function generateMetadata():Promise<Metadata> {
  const locale=await getLocale();
  return {title:{absolute:locale==='ar'?'إشعارات المتصفح · بيروت تايم':'Browser notifications · Beirut Time'}};
}
export { default } from '@/features/browser-push/page';
