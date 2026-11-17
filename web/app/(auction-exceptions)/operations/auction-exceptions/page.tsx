import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: { absolute: (await getLocale()) === 'ar' ? 'استثناءات المزاد · بيروت تايم' : 'Auction exceptions · Beirut Time' },
    robots: { index: false, follow: false },
  };
}

export { default } from '@/features/auction-exceptions/view';
