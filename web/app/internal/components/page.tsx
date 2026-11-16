import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import { ComponentBoard } from '@/internal/components/client';
import { reviewLocale, reviewMode } from '@/internal/components/model';
type Props = {searchParams:Promise<{data?:string|string[];locale?:string|string[]}>};
export async function generateMetadata({searchParams}:Props):Promise<Metadata> {
  const query = await searchParams, locale = reviewLocale(query.locale,await getLocale());
  return {title:{absolute:locale === 'ar' ? 'مكوّنات الواجهة · بيروت تايم' : 'Interface components · Beirut Time'},robots:{index:false,follow:false}};
}
/** Unlisted drawing board: new shared elements are composed here first. */
export default async function ComponentsPage({searchParams}:Props) {
  const query = await searchParams;
  return <ComponentBoard initialMode={reviewMode(query.data)} initialLocale={reviewLocale(query.locale,await getLocale())}/>;
}
