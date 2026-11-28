'use client';

import { useEffect, useState, useSyncExternalStore, type ReactNode } from 'react';
import { usePathname } from 'next/navigation';
import type { Locale } from '@/lib/i18n';
import type { NavEntry } from '@/registry-types';
import { useLocale } from './locale-context';
import { FoundationShell } from './foundation/shell';
import { shellPath } from './foundation/path';
import { clearPageReadMemory, rememberPageInput } from '@/lib/page-speed/memory';

const subscribe = () => () => {};
/** Server snapshot paints the trusted direct-load frame. After hydration the
 * committed router path, not a persistent root layout's initial path, owns it.
 * Language changes preserve this frame and its mounted forms. */
export function ShellBoundary({serverPath,children,locale:initialLocale,entries}: {serverPath:string;children:ReactNode;locale:Locale;entries:NavEntry[]}) {
  const [accessRevision, setAccessRevision] = useState(0);
  useEffect(()=>{const purge = ()=>{clearPageReadMemory();setAccessRevision(revision=>revision+1);};const keyboard = ()=>rememberPageInput('keyboard'), pointer = ()=>rememberPageInput('pointer');window.addEventListener('bt:access-change',purge);document.addEventListener('keydown',keyboard,true);document.addEventListener('pointerdown',pointer,true);
    return()=>{window.removeEventListener('bt:access-change',purge);document.removeEventListener('keydown',keyboard,true);document.removeEventListener('pointerdown',pointer,true);};
  },[]);
  const locale = useLocale(initialLocale);
  const committed = usePathname();
  const path = useSyncExternalStore(subscribe,()=>committed,()=>serverPath), route = shellPath(path ?? serverPath);
  return <FoundationShell locale={locale} entries={entries} path={route} accessRevision={accessRevision}>{children}</FoundationShell>;
}
