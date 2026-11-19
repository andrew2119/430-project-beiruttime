import { getLocale } from '@/shell/locale';
import { HomePage } from '@/shell/foundation/home';
import { navigation } from '@/registry-loader';
export default function Home() { return <HomePage entries={navigation}/>; }
export async function generateMetadata() { return {title:{absolute:(await getLocale()) === 'ar' ? 'لوحة التحكم · بيروت تايم' : 'Dashboard · Beirut Time'}}; }
