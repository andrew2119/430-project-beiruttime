import type { Metadata } from 'next';
import OperationsBoundary from '@/features/maintenance/intake/route';
import { getLocale } from '@/shell/locale';

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getLocale();
  return {
    title: { absolute: locale === 'ar' ? 'الاستلام الفني · بيروت تايم' : 'Technical intake · Beirut Time' },
    robots: { index: false, follow: false },
  };
}

export default function BusinessIntakePage() { return <OperationsBoundary screen="intake"/>; }
