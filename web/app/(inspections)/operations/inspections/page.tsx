import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import InspectionView from '@/features/private-inspection/view';

export async function generateMetadata():Promise<Metadata> {
  return {title:{absolute:(await getLocale()) === 'ar' ? 'الفحص المستقل للساعة · بيروت تايم' : 'Independent watch inspection · Beirut Time'},robots:{index:false,follow:false}};
}

export default function InspectionsPage() {
  return <InspectionView/>;
}
