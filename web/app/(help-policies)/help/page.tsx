import type { Metadata } from 'next';
import { getLocale } from '@/shell/locale';
import HelpPolicies from '@/features/help-policies/view';

export async function generateMetadata():Promise<Metadata> {
  return {title:{absolute:(await getLocale()) === 'ar' ? 'المساعدة والسياسات · بيروت تايم' : 'Help and policies · Beirut Time'}};
}
export default function HelpPage() {
  return <HelpPolicies/>;
}
