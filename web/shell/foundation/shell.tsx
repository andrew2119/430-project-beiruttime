'use client';

import { useCallback, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from 'react';
import Link from 'next/link';
import { Menu, Watch } from 'lucide-react';
import { DirectionProvider, Sheet, SheetContent, SheetTrigger, Toaster } from '@beirut-time/ui/foundation';
import type { Locale } from '@/lib/i18n';
import type { NavEntry } from '@/registry-types';
import { PageReadProvider } from '@/lib/page-speed/provider';
import { PageWarmingLoader } from '@/lib/page-speed/loader';
import { ShellNavigation } from './navigation';
import { ShellUpdates } from './updates';
import { LocaleControl } from './locale-control';
import { ShellProfile } from './profile';
import { SHELL_COPY } from './copy';
import { pageOwnsToasts } from './path';
import { fitVisualViewport } from './viewport';
const subscribeOnline = (run:()=>void)=>{window.addEventListener('online',run);window.addEventListener('offline',run);return()=>{window.removeEventListener('online',run);window.removeEventListener('offline',run);};};
const isOnline = ()=>navigator.onLine !== false;
const subscribePhone = (run:()=>void)=>{const media = window.matchMedia('(max-width: 850px)');media.addEventListener('change',run);return()=>media.removeEventListener('change',run);};
const isPhone = ()=>window.matchMedia('(max-width: 850px)').matches;
function BrandLink({locale}: {locale:Locale}) {return <Link href={`/${locale}`} prefetch={true} className="bt-shell-brand bt-pressable"><Watch aria-hidden="true"/><span>{SHELL_COPY[locale].brand}</span></Link>;}
/** Same frame exists in server HTML, while identity and route answers restore.
 * There is no auth animation or duplicate boot shell to hand off at hydration. */
export function FoundationShell({locale,entries,path,children,accessRevision=0}: {locale:Locale;entries:NavEntry[];path:string;children:ReactNode;accessRevision?:number}) {
  const t = SHELL_COPY[locale], content = useRef<HTMLElement|null>(null), previous = useRef(path);
  const [drawer,setDrawer] = useState<string|null>(null), navigating = useRef(false);
  const topbar = useRef<HTMLElement|null>(null), menuTrigger = useRef<HTMLButtonElement|null>(null), escaped = useRef(false);
  const online = useSyncExternalStore(subscribeOnline,isOnline,()=>true), phone = useSyncExternalStore(subscribePhone,isPhone,()=>false);
  const open = phone && drawer === path;
  const attachFrame = useCallback((node:HTMLDivElement|null)=>{if (node) return fitVisualViewport(node);},[]);
  useEffect(()=>{
    if (previous.current !== path) {previous.current = path;content.current?.focus({preventScroll:true});content.current?.scrollTo({top:0,behavior:'instant'});}
  },[path]);
  useEffect(()=>{
    const media = window.matchMedia('(min-width: 851px)');
    const resize = ()=>{if (media.matches && drawer === path) {navigating.current = true;setDrawer(null);content.current?.focus({preventScroll:true});}};
    media.addEventListener('change',resize);return()=>media.removeEventListener('change',resize);
  },[drawer,path]);
  return <DirectionProvider dir={locale === 'ar' ? 'rtl' : 'ltr'}><div ref={attachFrame} className="bt-shell" dir={locale === 'ar' ? 'rtl' : 'ltr'} lang={locale}>
    <a href="#main-content" className="bt-shell-skip">{t.skip}</a>
    {!phone && <aside className="bt-shell-rail"><BrandLink locale={locale}/><ShellNavigation entries={entries} locale={locale} path={path}/><ShellProfile locale={locale} path={path}/></aside>}
    <header ref={topbar} className="bt-shell-topbar"><Sheet open={open} onOpenChange={value=>{if (value) {menuTrigger.current = topbar.current?.querySelector<HTMLButtonElement>('button[aria-haspopup="dialog"]') ?? null;escaped.current = false;}navigating.current = false;setDrawer(value ? path : null);}}><SheetTrigger label={t.menu}><Menu aria-hidden="true"/></SheetTrigger>
      <SheetContent form="end" title={t.navigation} closeLabel={t.close} className="bt-navigation-sheet" onEscapeKeyDown={()=>{escaped.current = true;}} onCloseAutoFocus={event=>{if (navigating.current || drawer != null && drawer !== path) {event.preventDefault();return;}if (escaped.current && menuTrigger.current?.isConnected) {event.preventDefault();menuTrigger.current.focus({preventScroll:true});}escaped.current = false;}}>
        {/* Close in the bubble phase, after the link's own handler has started the in-app navigation: closing earlier unmounts the link first, and the browser then does a full page load. */}
        {phone && <div className="bt-shell-drawer-content" role="presentation" onClick={event=>{const anchor = event.target instanceof Element ? event.target.closest('a[href]') : null;if (anchor && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) {navigating.current = true;setDrawer(null);}}}><BrandLink locale={locale}/><ShellNavigation entries={entries} locale={locale} path={path}/><ShellProfile locale={locale} path={path}/></div>}
      </SheetContent></Sheet><BrandLink locale={locale}/><LocaleControl locale={locale}/></header>
    <PageReadProvider key={accessRevision}><main ref={content} id="main-content" className="pg-tray bt-shell-content" tabIndex={-1}>{!online && <p role="status" className="bt-shell-connectivity">{t.offline}</p>}<ShellUpdates locale={locale}/>{children}</main><PageWarmingLoader/></PageReadProvider>
  </div>{!pageOwnsToasts(path) && <Toaster label={t.toasts} dismissLabel={t.dismiss} contentRef={content}/>}</DirectionProvider>;
}
