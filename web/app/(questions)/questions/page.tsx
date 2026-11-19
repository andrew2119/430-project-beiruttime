import { getLocale } from '@/shell/locale';

export async function generateMetadata() {
 const locale=await getLocale();
 return {title:locale==='ar'?'أسئلة الإعلان · بيروت تايم':'Listing questions · Beirut Time'};
}
export { default } from '@/features/listing-questions/view';
