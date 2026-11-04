import type { Metadata, Viewport } from 'next';
import { cookies } from 'next/headers';
import { direction } from '@/lib/i18n';
import { getLocale } from '@/shell/locale';
import { Shell } from '@/shell/shell';
import { Providers } from '@/shell/providers';
import './globals.css';
export async function generateMetadata(): Promise<Metadata> {
  const locale = await getLocale();
  return { title: { default: locale==='ar'?'بيروت تايم — للوقت حُسن الاختيار':'Beirut Time — Time well chosen', template: locale==='ar'?'%s · بيروت تايم':'%s · Beirut Time' }, description: locale==='ar'?'سوق الساعات المستقل في لبنان.':'Lebanon’s independent watch marketplace.', manifest: `/${locale}/manifest.webmanifest`, applicationName: 'Beirut Time', appleWebApp: { capable: true, statusBarStyle: 'default', title: 'Beirut Time' }, icons: { apple: '/icons/bt-192.png', icon: '/icons/bt-192.png' }, formatDetection: { telephone: false } };
}
export const viewport: Viewport = { width: 'device-width', initialScale: 1, viewportFit: 'cover', themeColor: '#173c34' };
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const theme = (await cookies()).get('bt-theme')?.value === 'dark' ? 'dark' : 'light';
  return <html lang={locale} dir={direction(locale)} data-theme={theme} style={{ colorScheme: theme }}><body><Providers locale={locale}><Shell locale={locale} theme={theme}>{children}</Shell></Providers></body></html>;
}
