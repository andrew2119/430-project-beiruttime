import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import History from '@/features/service-history/view';
export async function generateMetadata(): Promise<Metadata> { return {title:{absolute:await getLocale()==='ar'?'سجل الصيانة والتعديلات · بيروت تايم':'Service and modification history · Beirut Time'}}; }
export default function HistoryPage() { return <History/>; }
