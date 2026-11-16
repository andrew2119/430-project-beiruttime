'use client';
import type {ReactNode} from 'react';
import type {Area,NavEntry,Registration} from '@/registry-types';
import {DesktopNavigation} from './navigation';
import {messages,type Locale} from '@/lib/i18n';
import {ProfileBlock} from './profile-block';
import {RouteFocus} from './route-focus';
import {PhoneMenuButton,PhoneNavigation} from './phone-navigation';
import {Brand} from './brand';
import {Pwa} from './pwa';
import {AppToaster} from './toaster';
import {useLocale} from './locale-context';
export function ShellView({children,area,navigation,routes,initialLocale}:{children:ReactNode;area:Area;navigation:NavEntry[];routes:Registration['routes'];initialLocale:Locale}){
  const locale=useLocale(initialLocale),t=messages(locale);
  const sidebar=<aside className="pg-rail"><Brand locale={locale} label={t.brand}/><DesktopNavigation entries={navigation} routes={routes} locale={locale} label={t.navigation}/><ProfileBlock locale={locale}/></aside>;
  return <><div className={`pg-shell shell-${area}`}>
    <a className="pg-skip-link" href="#main-content">{t.skip}</a>
    {sidebar}
    <header className="pg-mobile-topbar"><PhoneMenuButton label={t.menu}/><Brand locale={locale} label={t.brand}/></header>
    <RouteFocus/>
    <div className="pg-tray-frame"><main id="main-content" tabIndex={-1} className="pg-tray main-content"><Pwa t={t}/>{children}</main></div>
    <PhoneNavigation entries={navigation} routes={routes} locale={locale} t={t} sidebar={sidebar}/>
  </div><AppToaster locale={locale}/></>;
}
