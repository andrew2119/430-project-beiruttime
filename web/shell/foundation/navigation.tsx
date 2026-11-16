'use client';
import type { Area, NavEntry } from '@/registry-types';
import type { Locale } from '@/lib/i18n';
import { useAccessContext } from '@/shell/access-context';
import { navigationIcons, type NavigationDestination } from '@/shell/navigation-icon';
import { DestinationLink } from './destination';
import { SHELL_COPY } from './copy';
import { shellPath } from './path';
const AREAS:Area[] = ['storefront','account','seller','operator'];
export function ShellNavigation({entries,locale,path}: {entries:NavEntry[];locale:Locale;path:string}) {
  const access = useAccessContext(), t = SHELL_COPY[locale];
  const labels = {storefront:t.market,account:t.account,seller:t.selling,operator:t.operations};
  return <nav className="bt-shell-navigation" aria-label={t.navigation} data-bt-glance="">{AREAS.map(area=>{
    const visible = entries.filter(entry=>entry.area === area && !['account','settings'].includes(entry.id) && entry.roles.some(role=>role === 'public' || access.roles.includes(role)));
    return visible.length ? <section key={area} className="bt-navigation-group" aria-label={labels[area]}><h2 className="bt-caption">{labels[area]}</h2>{visible.map(entry=><DestinationLink key={entry.id} href={`/${locale}${entry.href}`} label={entry.label[locale]} icon={entry.id in navigationIcons ? entry.id as NavigationDestination : 'account'} active={shellPath(path) === entry.href} path={path}/>)}</section> : null;
  })}</nav>;
}
