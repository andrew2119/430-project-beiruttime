import { DealerImport } from '@/features/dealer-import/view';
import { getLocale } from '@/shell/locale';
export async function generateMetadata() { return {title:(await getLocale())==='ar'?'استيراد الوكيل · بيروت تايم':'Dealer import · Beirut Time'}; }
export default function Page() { return <DealerImport/>; }
