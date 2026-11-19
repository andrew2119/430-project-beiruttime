import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import SavedPage from '@/features/saved-watches/page';
export async function generateMetadata():Promise<Metadata> {
  return {title:{absolute:(await getLocale())==='ar'?'الساعات المحفوظة · بيروت تايم':'Saved watches · Beirut Time'},robots:{index:false,follow:false}};
}
export default function Page() {return <SavedPage/>;}
