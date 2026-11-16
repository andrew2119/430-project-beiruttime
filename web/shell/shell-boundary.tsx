'use client';

import { useEffect, useRef, useSyncExternalStore, type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import type { Locale } from '@/lib/i18n';
import type { NavEntry } from '@/registry-types';
import { FoundationShell } from './foundation/shell';
import { shellForPath, shellPath, usesFoundationShell } from './foundation/path';
import { clearPageReadMemory, rememberPageInput } from '@/lib/page-speed/memory';

const subscribe = () => () => {};
/** Server snapshot paints the trusted direct-load frame. After hydration the
 * committed router path, not a persistent root layout's initial path, owns it.
 * Providers stay above this single exclusive choice in both directions. */
export function ShellBoundary({serverPath,legacy,children,locale,entries}: {serverPath:string;legacy:ReactNode;children:ReactNode;locale:Locale;entries:NavEntry[]}) {
  useEffect(()=>{const keyboard = ()=>rememberPageInput('keyboard'), pointer = ()=>rememberPageInput('pointer');window.addEventListener('bt:access-change',clearPageReadMemory);document.addEventListener('keydown',keyboard,true);document.addEventListener('pointerdown',pointer,true);
    return()=>{window.removeEventListener('bt:access-change',clearPageReadMemory);document.removeEventListener('keydown',keyboard,true);document.removeEventListener('pointerdown',pointer,true);};
  },[]);
  const committed = usePathname();
  const path = useSyncExternalStore(subscribe,()=>committed,()=>serverPath), route = shellPath(path ?? serverPath), previous = useRef(route);
  useEffect(()=>{if (usesFoundationShell(previous.current) !== usesFoundationShell(route)) {const main = document.getElementById('main-content');main?.focus({preventScroll:true});main?.scrollTo({top:0,behavior:'instant'});}previous.current = route;},[route]);
  return shellForPath(serverPath,path) === 'foundation'
    ? <FoundationShell locale={locale} entries={entries} path={route}>{children}</FoundationShell>
    : legacy;
}
