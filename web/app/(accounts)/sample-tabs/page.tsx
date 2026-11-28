import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import SampleTabsView from '@/features/identity/sample-tabs';
export async function generateMetadata(): Promise<Metadata> {
  return {
    title: {absolute: (await getLocale()) === 'ar' ? 'علامات التبويب التجريبية · بيروت تايم' : 'Sample tabs · Beirut Time'},
    robots: {index: false, follow: false},
  };
}
export default function SampleTabsPage() { return <SampleTabsView/>; }
