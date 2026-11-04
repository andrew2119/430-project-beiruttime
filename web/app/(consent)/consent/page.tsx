import ConsentView from '@/features/consent/consent-view';
import { getLocale } from '@/shell/locale';
export async function generateMetadata() { return { title: await getLocale() === 'ar' ? 'الموافقة الخاصة على التحقق' : 'Private identity consent' }; }
export default async function ConsentPage({ searchParams }: { searchParams: Promise<{ request?: string; brand?: string; revision?: string }> }) {
  const params = await searchParams;
  const uuid = (value?: string) => value && /^[a-fA-F0-9-]{36}$/.test(value) ? value : undefined;
  return <ConsentView binding={{ request: uuid(params.request), brand: uuid(params.brand), revision: params.revision && /^[0-9٠-٩۰-۹]{1,9}$/.test(params.revision) ? params.revision : undefined }}/>;
}
