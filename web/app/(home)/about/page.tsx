import { getLocale } from '@/shell/locale';
import { AboutPage } from '@/shell/foundation/about';
export default function About() { return <AboutPage/>; }
export async function generateMetadata() { return {title:{absolute:(await getLocale()) === 'ar' ? 'عن بيروت تايم · بيروت تايم' : 'About · Beirut Time'}}; }
