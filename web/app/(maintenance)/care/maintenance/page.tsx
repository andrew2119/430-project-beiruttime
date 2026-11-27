import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import MaintenanceRequest from '@/features/maintenance/request';
export default function MaintenancePage() { return <MaintenanceRequest/>; }
export async function generateMetadata():Promise<Metadata> {return {title:{absolute:(await getLocale())==='ar'?'طلب صيانة · بيروت تايم':'Request maintenance · Beirut Time'},robots:{index:false,follow:false}};}
