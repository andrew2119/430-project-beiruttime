import type { Metadata, Viewport } from 'next';
import { cookies } from 'next/headers';
import localFont from 'next/font/local';
import { parseTheme, THEME_COOKIE } from '@/lib/theme';
import { ThemeProvider } from '@/shell/theme-provider';
import { BRAND_THEME_COLOR } from '@/lib/brand';
import { direction } from '@/lib/i18n';
import { getLocale, getPublicPath } from '@/shell/locale';
import { FoundationProviders } from '@/shell/foundation/providers';
import { ShellBoundary } from '@/shell/shell-boundary';
import { navigation } from '@/registry-loader';
import './globals.css';
const lexendDeca = localFont({ src: './fonts/lexend-deca.ttf', variable: '--font-lexend-deca', weight: '100 900', display: 'swap', adjustFontFallback: false, fallback: [] });
const arabic = localFont({ src: './fonts/noto-sans-arabic.ttf', variable: '--font-arabic', weight: '100 900', display: 'swap', preload: false });
export async function generateMetadata(): Promise<Metadata> {
  const locale = await getLocale();
  return { title: { default: locale==='ar'?'للوقت حُسن الاختيار · بيروت تايم':'Time well chosen · Beirut Time', template: locale==='ar'?'%s · بيروت تايم':'%s · Beirut Time' }, description: locale==='ar'?'سوق الساعات المستقل في لبنان.':'Lebanon’s independent watch marketplace.', manifest: `/${locale}/manifest.webmanifest`, applicationName: 'Beirut Time', appleWebApp: { capable: true, statusBarStyle: 'default', title: 'Beirut Time' }, icons: { apple: '/icons/bt-192.png', icon: '/icons/bt-192.png' }, formatDetection: { telephone: false } };
}
export const viewport: Viewport = { width: 'device-width', initialScale: 1, viewportFit: 'cover', themeColor: BRAND_THEME_COLOR };
export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await getLocale();
  const theme = parseTheme((await cookies()).get(THEME_COOKIE)?.value);
  const path = await getPublicPath();
  return <html lang={locale} dir={direction(locale)} data-theme={theme} className={[lexendDeca.variable, arabic.variable].join(' ')}><body><ThemeProvider initialTheme={theme}><FoundationProviders locale={locale}><ShellBoundary serverPath={path} locale={locale} entries={navigation}>{children}</ShellBoundary></FoundationProviders></ThemeProvider></body></html>;
}
