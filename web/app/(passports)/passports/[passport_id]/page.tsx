import { getLocale } from '@/shell/locale';
import { PassportPage } from '@/features/passports/page';

export async function generateMetadata() {
  const locale = await getLocale();
  return {title:{absolute:locale === 'ar' ? 'التحقق من ملخص الفحص · بيروت تايم' : 'Verify inspection summary · Beirut Time'}};
}

export default async function Page({params}:{params:Promise<{passport_id:string}>}) {
  const {passport_id} = await params;
  return <PassportPage id={passport_id}/>;
}
