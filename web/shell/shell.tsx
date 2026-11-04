import Link from 'next/link';
import { navigation, registeredRoutes } from '@/registry-loader';
import { DesktopNavigation } from './navigation';
import { messages, type Locale } from '@/lib/i18n';
import { Preferences } from './preferences';
import { RouteFocus } from './route-focus';
import { PhoneMenuButton, PhoneNavigation } from './phone-navigation';
import { Pwa } from './pwa';
export function Shell({ children, locale, theme, area = 'storefront' }: { children: React.ReactNode; locale: Locale; theme: 'light' | 'dark'; area?: 'storefront' | 'account' | 'seller' | 'operator' }) {
  const t = messages(locale);
  const entries = navigation;
  return <div className={`shell shell-${area}`}>
    <a className="skip-link" href="#main-content">{t.skip}</a>
    <header className="masthead">
      <PhoneMenuButton label={t.menu}/>
      <Link href={`/${locale}`} className="brand" aria-label={t.brand}><span className="brand-mark" aria-hidden="true">BT</span><span>{t.brand}<small>{locale === 'ar' ? 'بيروت · لبنان' : 'BEIRUT · LEBANON'}</small></span></Link>
      <DesktopNavigation entries={entries} routes={registeredRoutes} locale={locale} label={t.navigation}/>
      <Preferences locale={locale} theme={theme} t={t} />
    </header>
    <RouteFocus />
    <main id="main-content" tabIndex={-1} className="main-content">{children}
      <footer className="footer"><p>{t.footer}</p><Pwa t={t} /></footer>
    </main>
    <PhoneNavigation entries={entries} routes={registeredRoutes} locale={locale} t={t} />
  </div>;
}
