import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import { StartingPage } from '@/internal/page/view';
export async function generateMetadata():Promise<Metadata> {return {title:{absolute:(await getLocale()) === 'ar' ? 'نقطة بداية الصفحة · بيروت تايم' : 'Page starting point · Beirut Time'},robots:{index:false,follow:false}};}
export default async function Page() {return <StartingPage locale={await getLocale()}/>;}
