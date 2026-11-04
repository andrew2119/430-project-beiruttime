'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef } from 'react';
import type { NavEntry } from '@/registry-types';
import type { Locale, Messages } from '@/lib/i18n';
import { Button } from './primitives';
import { useAccessContext } from './access-context';
import { localizePath } from './paths';
import { areaForPath, permittedEntries, type RouteEntry } from './navigation';
let menuInvoker: HTMLButtonElement | null = null;
let menuNavigating = false;
function openMenu(invoker: HTMLButtonElement) { menuInvoker=invoker; menuNavigating=false; document.querySelector<HTMLDialogElement>('.phone-drawer')?.showModal(); }
export function PhoneMenuButton({ label }: { label: string }) {
  return <Button className="icon-button top-menu" aria-label={label} aria-haspopup="dialog" aria-controls="phone-menu" onClick={event => openMenu(event.currentTarget)}><span aria-hidden="true">☰</span></Button>;
}
export function PhoneNavigation({ entries, routes, locale, t }: { entries: NavEntry[]; routes: RouteEntry[]; locale: Locale; t: Messages }) {
  const path = usePathname();
  const access = useAccessContext();
  const allowed = permittedEntries(entries, access.roles);
  const bottom = permittedEntries(entries, access.roles, areaForPath(path,routes)).filter(n=>n.bottom).slice(0,4);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    // CP F-40/F-41: CSS and JS share exactly 850px. Keep page children mounted.
    const media = window.matchMedia('(max-width: 850px)');
    const resize = () => { if (!media.matches && dialog.current?.open) { menuNavigating=true; dialog.current.close(); document.getElementById('main-content')?.focus({preventScroll:true}); } };
    media.addEventListener('change', resize);
    const vv = window.visualViewport;
    const keyboard = () => {
      const focused = document.activeElement?.matches('input,textarea,[contenteditable="true"]');
      document.documentElement.toggleAttribute('data-keyboard-open', !!(media.matches && focused && vv && vv.scale === 1 && vv.height < innerHeight * .8));
    };
    vv?.addEventListener('resize', keyboard);
    document.addEventListener('focusin', keyboard);
    document.addEventListener('focusout', keyboard);
    return () => {
      media.removeEventListener('change', resize);
      vv?.removeEventListener('resize', keyboard);
      document.removeEventListener('focusin', keyboard);
      document.removeEventListener('focusout', keyboard);
      document.documentElement.removeAttribute('data-keyboard-open');
    };
  }, []);
  return <>
    <nav className="bottom-nav" aria-label={t.navigation} style={{ gridTemplateColumns: `repeat(${bottom.length + 1},minmax(0,1fr))` }}>
      {bottom.map((n, i) => <Link key={n.id} href={`/${locale}${n.href}`} aria-current={localizePath(path,locale) === `/${locale}${n.href}` ? 'page' : undefined}><span aria-hidden="true">{['⌂','◷','◇','○'][i]}</span>{n.label[locale]}</Link>)}
      <Button className="bottom-menu" aria-haspopup="dialog" aria-controls="phone-menu" onClick={event => openMenu(event.currentTarget)}><span aria-hidden="true">☰</span>{t.menu}</Button>
    </nav>
    <dialog id="phone-menu" ref={dialog} className="phone-drawer" aria-labelledby="menu-title" onClose={() => { if(!menuNavigating && menuInvoker?.isConnected) menuInvoker.focus(); }} onClick={e => { const rect=e.currentTarget.getBoundingClientRect(); if(e.target===e.currentTarget && (e.clientX<rect.left||e.clientX>rect.right||e.clientY<rect.top||e.clientY>rect.bottom)) dialog.current?.close(); }}>
      <div className="drawer-heading"><h2 id="menu-title">{t.brand}</h2><Button aria-label={t.close} className="icon-button" onClick={() => dialog.current?.close()}>×</Button></div>
      <nav aria-label={t.navigation}>{allowed.map(n => <Link key={n.id} href={`/${locale}${n.href}`} onClick={() => {
        // Bubble after Next's link handler; destination focus has one owner (CP mobile §6.2).
        menuNavigating=localizePath(path,locale)!==`/${locale}${n.href}`;
        dialog.current?.close();
      }}>{n.label[locale]}</Link>)}</nav>
    </dialog>
  </>;
}
