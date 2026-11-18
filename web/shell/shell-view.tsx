'use client';
import type { ReactNode } from 'react';
import type { Area, NavEntry, Registration } from '@/registry-types';
import type { Locale } from '@/lib/i18n';
import { usePathname } from 'next/navigation';
import { ShellBoundary } from './shell-boundary';
export function ShellView({children,navigation,initialLocale}: {children:ReactNode;area:Area;navigation:NavEntry[];routes:Registration['routes'];initialLocale:Locale}) {
  const path = usePathname();
  return <ShellBoundary serverPath={path} locale={initialLocale} entries={navigation}>{children}</ShellBoundary>;
}
