import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import SecurityView from '@/features/two-factor/view';

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: {absolute: (await getLocale()) === 'ar' ? 'أمان الحساب · بيروت تايم' : 'Account security · Beirut Time'},
    robots: {index: false, follow: false},
  };
}

export default function SecurityPage() {
  return <SecurityView/>;
}
