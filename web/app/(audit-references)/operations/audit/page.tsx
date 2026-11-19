import { getLocale } from '@/shell/locale';
import AuditScreen from '@/features/audit-references/screen';
export default function AuditPage() { return <AuditScreen/>; }
export async function generateMetadata() {
  return {title:{absolute:(await getLocale())==='ar'?'مراجع التدقيق التشغيلي · بيروت تايم':'Operational audit references · Beirut Time'},robots:{index:false,follow:false}};
}
