'use client';

import { createContext, useContext, useState, type ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { useAccessContext } from '@/shell/access-context';
import type { ReadScope } from './scope';
import { pageReadMemory } from './memory';
const Scope = createContext<ReadScope|null>(null);
function ScopedReads({scopeKey,children}: {scopeKey:string;children:ReactNode}) {
  const [scope] = useState(()=>pageReadMemory(scopeKey));
  return <Scope value={scope}><QueryClientProvider client={scope.client}>{children}</QueryClientProvider></Scope>;
}
/** Identity/access alone replaces this cache. Locale and route never key it.
 * Live Sprint 1 providers and their clocks are untouched above the boundary. */
export function PageReadProvider({children}: {children:ReactNode}) {
  const access = useAccessContext();
  const key = access.fingerprint == null ? 'public' : `member:${access.fingerprint}`;
  return <ScopedReads key={key} scopeKey={key}>{children}</ScopedReads>;
}
export function usePageReadScope() {const scope = useContext(Scope);if (!scope) throw new Error('Page reads require the shared page scope');return scope;}
