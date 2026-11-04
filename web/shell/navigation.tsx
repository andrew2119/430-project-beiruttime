'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { Area, NavEntry, Registration, Role } from '@/registry-types';
import type { Locale } from '@/lib/i18n';
import { useAccessContext } from './access-context';
import { localizePath, stripLocale } from './paths';
export type RouteEntry = Registration['routes'][number];
export function areaForPath(path: string, routes: RouteEntry[]): Area {
  const parts=stripLocale(path).split('/').filter(Boolean);
  return routes.find(route=>{const pattern=route.path.split('/').filter(Boolean);return pattern.length===parts.length && pattern.every((part,i)=>part===parts[i]||part.startsWith(':')||/^\[\w+\]$/.test(part));})?.area ?? 'storefront';
}
export function permittedEntries(entries: NavEntry[], roles: Role[], area?: Area) { return entries.filter(n=>(!area||n.area===area) && n.roles.some(role=>role==='public'||roles.includes(role))); }
export function DesktopNavigation({entries,routes,locale,label}:{entries:NavEntry[];routes:RouteEntry[];locale:Locale;label:string}) {
  const path=usePathname(), access=useAccessContext();
  const visible=permittedEntries(entries,access.roles,areaForPath(path,routes));
  return <nav className="desktop-nav" aria-label={label}>{visible.filter(n=>n.id!=='home').map(n=><Link key={n.id} href={`/${locale}${n.href}`} aria-current={localizePath(path,locale)===`/${locale}${n.href}`?'page':undefined}>{n.label[locale]}</Link>)}</nav>;
}
