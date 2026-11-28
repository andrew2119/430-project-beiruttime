import { getLocale } from '@/shell/locale';
import { PageLoading } from '@/shell/foundation/page';
export default async function Loading() {return <PageLoading label={(await getLocale()) === 'ar' ? 'جارٍ تحميل الصفحة' : 'Loading page'}/>;}
