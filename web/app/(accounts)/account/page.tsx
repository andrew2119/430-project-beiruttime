import AccountView from '@/features/identity/account-view';
import { getLocale } from '@/shell/locale';
export async function generateMetadata() { return { title: await getLocale() === 'ar' ? 'حسابي' : 'Account' }; }
export default async function AccountPage({ searchParams }: { searchParams: Promise<{ mode?: string }> }) {
  const { mode } = await searchParams;
  return <AccountView initialMode={mode === 'reset' ? 'reset' : 'signin'}/>;
}
