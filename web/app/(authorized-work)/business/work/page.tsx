import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import AuthorizedWork from '@/features/authorized-work/view';

export async function generateMetadata(): Promise<Metadata> {
  return {title:{absolute:(await getLocale()) === 'ar' ? 'العمل المصرح به · بيروت تايم' : 'Authorized work · Beirut Time'},robots:{index:false,follow:false}};
}
export default function Page() { return <AuthorizedWork/>; }
