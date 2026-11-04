import { navigation, registeredRoutes } from '@/registry-loader';
import { DesktopNavigation } from './navigation';
import { messages, type Locale } from '@/lib/i18n';
import { ProfileBlock } from './profile-block';
import { RouteFocus } from './route-focus';
import { PhoneMenuButton, PhoneNavigation } from './phone-navigation';
import { Brand } from './brand';
import { Pwa } from './pwa';
import { AppToaster } from './toaster';
export function Shell({ children, locale, area = 'storefront' }: { children: React.ReactNode; locale: Locale; theme: 'light' | 'dark'; area?: 'storefront' | 'account' | 'seller' | 'operator' }) {
  const t=messages(locale);
  const sidebar=<aside className="pg-rail"><Brand locale={locale} label={t.brand}/><DesktopNavigation entries={navigation} routes={registeredRoutes} locale={locale} label={t.navigation}/><ProfileBlock locale={locale}/></aside>;
  return <><div className={`pg-shell shell-${area}`}>
    <a className="pg-skip-link" href="#main-content">{t.skip}</a>
    {sidebar}
    <header className="pg-mobile-topbar"><PhoneMenuButton label={t.menu}/><Brand locale={locale} label={t.brand}/></header>
    <RouteFocus/>
    <div className="pg-tray-frame"><main id="main-content" tabIndex={-1} className="pg-tray main-content"><Pwa t={t}/>{children}</main></div>
    <PhoneNavigation entries={navigation} routes={registeredRoutes} locale={locale} t={t} sidebar={sidebar}/>
  </div><AppToaster locale={locale}/></>;
}
