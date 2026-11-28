import { State } from '@beirut-time/ui/foundation';
import { getLocale } from '@/shell/locale';
import { PageBody } from '@/shell/foundation/page';
export default async function NotFound() {const ar = (await getLocale()) === 'ar';return <PageBody><State title={ar ? 'الصفحة غير موجودة' : 'Page not found'} body={ar ? 'لا توجد صفحة في هذا العنوان.' : 'There is no page at this address.'}/></PageBody>;}
