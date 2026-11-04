'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useState } from 'react';
import type { Area, NavEntry, Registration, Role } from '@/registry-types';
import type { Locale } from '@/lib/i18n';
import { useAccessContext } from './access-context';
import { localizePath, stripLocale } from './paths';
import { PendingRouteIcon } from './route-icon';
export type RouteEntry = Registration['routes'][number];
export function areaForPath(path: string, routes: RouteEntry[]): Area {
  const parts=stripLocale(path).split('/').filter(Boolean);
  return routes.find(route=>{const pattern=route.path.split('/').filter(Boolean);return pattern.length===parts.length && pattern.every((part,i)=>part===parts[i]||part.startsWith(':')||/^\[\w+\]$/.test(part));})?.area ?? 'storefront';
}
export function permittedEntries(entries: NavEntry[], roles: Role[], area?: Area) { return entries.filter(n=>(!area||n.area===area) && n.roles.some(role=>role==='public'||roles.includes(role))); }
const areaLabels: Record<Area, Record<Locale,string>> = { storefront: { en: 'Marketplace', ar: 'السوق' }, account: { en: 'Account', ar: 'الحساب' }, seller: { en: 'Selling', ar: 'البيع' }, operator: { en: 'Operations', ar: 'العمليات' } };
/** CP's section rows, backed by Beirut Time's unchanged permission registry. */
export function DesktopNavigation({entries,routes,locale,label}:{entries:NavEntry[];routes:RouteEntry[];locale:Locale;label:string}) {
  const path=usePathname(), access=useAccessContext();
  const [warm,setWarm]=useState(false);
  useEffect(()=>{
    if(typeof window.requestIdleCallback==='function'){const id=requestIdleCallback(()=>setWarm(true),{timeout:2000});return()=>cancelIdleCallback(id);}
    const id=setTimeout(()=>setWarm(true),2000);return()=>clearTimeout(id);
  },[]);
  const visible=permittedEntries(entries,access.roles);
  const current=areaForPath(path,routes);
  const groups: Area[] = [current, ...(['storefront','account','seller','operator'] as Area[]).filter(area=>area!==current)];
  return <nav aria-label={label} className="pg-sidebar-nav">{groups.map(area=>{
    const items=visible.filter(n=>n.area===area && n.id!=='account' && n.id!=='settings');
    return items.length ? <div key={area} className="pg-sidebar-section"><div className="pg-nav-heading">{areaLabels[area][locale]}</div><div className="pg-nav-group">{items.map(n=>{
      const href=`/${locale}${n.href}`;
      const localized=localizePath(path,locale);
      const active=localized===href || (n.href!=='' && localized.startsWith(`${href}/`));
      return <Link key={n.id} href={href} prefetch={warm} aria-current={active?'page':undefined} className="pg-nav-item pg-nav-row"><PendingRouteIcon id={n.id} href={n.href} active={active}/><span className="pg-nav-label">{n.label[locale]}</span></Link>;
    })}</div></div> : null;
  })}</nav>;
}
