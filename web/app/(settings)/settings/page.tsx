import { getLocale } from '@/shell/locale';
import { SettingsPage } from '@/shell/settings';
export default function Settings() { return <SettingsPage/>; }
export async function generateMetadata() { return {title:{absolute:(await getLocale()) === 'ar' ? 'الإعدادات · بيروت تايم' : 'Settings · Beirut Time'}}; }
