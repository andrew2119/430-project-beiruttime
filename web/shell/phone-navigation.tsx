'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef, useSyncExternalStore, type ReactNode } from 'react';
import { Menu, X } from 'lucide-react';
import type { NavEntry } from '@/registry-types';
import type { Locale, Messages } from '@/lib/i18n';
import { Sheet, SheetContent, SheetTitle, SheetClose } from '@beirut-time/ui';
import { useAccessContext } from './access-context';
import { localizePath } from './paths';
import { areaForPath, permittedEntries, type RouteEntry } from './navigation';
import { RouteIcon } from './route-icon';
// One drawer, two doors, with one SSR-safe external store.
let drawer = { open: false, path: '' };
let drawerInvoker: HTMLButtonElement | null = null;
function openDrawer(path: string, invoker: HTMLButtonElement) {
  drawerInvoker = invoker;
  setDrawer({ open: true, path });
}
const closed = { open: false, path: '' };
const listeners = new Set<() => void>();
function setDrawer(next: typeof drawer) { drawer=next; listeners.forEach(listener=>listener()); }
function subscribe(listener: () => void) { listeners.add(listener); return ()=>{listeners.delete(listener);}; }
function useDrawer() { return useSyncExternalStore(subscribe,()=>drawer,()=>closed); }
export function PhoneMenuButton({ label }: { label: string }) {
  const path=usePathname(), state=useDrawer();
  return <button type="button" className="pg-mobile-menu" aria-label={label} aria-haspopup="dialog" aria-expanded={state.open && state.path===path} aria-controls="phone-menu" onClick={event=>openDrawer(path,event.currentTarget)}><Menu aria-hidden="true"/></button>;
}
export function PhoneNavigation({ entries, routes, locale, t, sidebar }: { entries: NavEntry[]; routes: RouteEntry[]; locale: Locale; t: Messages; sidebar: ReactNode }) {
  const path=usePathname(), state=useDrawer(), navigating=useRef(false);
  const access=useAccessContext();
  const bottom=permittedEntries(entries,access.roles,areaForPath(path,routes)).filter(n=>n.bottom).slice(0,4);
  const open=state.open && state.path===path;
  useEffect(()=>{
    const media=window.matchMedia('(max-width: 850px)');
    const resize=()=>{ if(!media.matches && drawer.open) { navigating.current=true; setDrawer(closed); requestAnimationFrame(()=>document.getElementById('main-content')?.focus({preventScroll:true})); } };
    media.addEventListener('change',resize);
    const vv=window.visualViewport;
    const keyboard=()=>{ const focused=document.activeElement?.matches('input:not([type="checkbox"]):not([type="radio"]),textarea,[contenteditable="true"]'); document.documentElement.toggleAttribute('data-keyboard-open',!!(media.matches && focused && vv && vv.scale===1 && vv.height<innerHeight*.8)); };
    vv?.addEventListener('resize',keyboard); document.addEventListener('focusin',keyboard); document.addEventListener('focusout',keyboard);
    return ()=>{ media.removeEventListener('change',resize); vv?.removeEventListener('resize',keyboard); document.removeEventListener('focusin',keyboard); document.removeEventListener('focusout',keyboard); document.documentElement.removeAttribute('data-keyboard-open'); setDrawer(closed); };
  },[]);
  return <>
    <nav className="pg-mobile-dock" aria-label={t.navigation}>{bottom.map(n=>{
      const active=localizePath(path,locale)===`/${locale}${n.href}`;
      return <Link key={n.id} href={`/${locale}${n.href}`} aria-current={active?'page':undefined}><RouteIcon id={n.id} href={n.href}/><span>{n.label[locale]}</span></Link>;
    })}<button type="button" className="psb-dock-menu" aria-haspopup="dialog" aria-controls="phone-menu" aria-expanded={open} data-current={open || undefined} onClick={event=>openDrawer(path,event.currentTarget)}><Menu aria-hidden="true"/><span>{t.menu}</span></button></nav>
    <Sheet open={open} onOpenChange={open=>{navigating.current=false;setDrawer({open,path});}}><SheetContent id="phone-menu" className="pg-mobile-drawer psb-drawer" aria-describedby={undefined} onOpenAutoFocus={()=>{navigating.current=false;}} onCloseAutoFocus={event=>{
      // Neither door is a Radix Trigger: restore the actual invoker explicitly.
      event.preventDefault();
      if(!navigating.current && state.path===path && drawerInvoker?.isConnected) drawerInvoker.focus({preventScroll:true});
    }} onClick={event=>{
      const link=(event.target as Element).closest<HTMLAnchorElement>('a[href]');
      if(link && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) { navigating.current=new URL(link.href).pathname!==path; setDrawer({open:false,path}); }
    }}><SheetTitle className="sr-only">{t.navigation}</SheetTitle><SheetClose className="pg-mobile-close" aria-label={t.close}><X aria-hidden="true"/></SheetClose>{sidebar}</SheetContent></Sheet>
  </>;
}
