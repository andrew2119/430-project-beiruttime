'use client';
import { useEffect, useRef } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { usePageReadScope } from './provider';
import { refreshPageReads } from './read';
import { startPageWarming } from './engine';
import { setPageWarmingRunning } from './running';
export function PageWarmingMount() {
  const router = useRouter(), scope = usePageReadScope(), path = usePathname(), query = useSearchParams().toString();
  const engine = useRef<ReturnType<typeof startPageWarming>|null>(null), previous = useRef(`${path}?${query}`);
  useEffect(()=>{const running = startPageWarming(router,scope);engine.current = running;setPageWarmingRunning(true, running.ownsGlance);return()=>{running.stop();engine.current = null;setPageWarmingRunning(false);};},[router,scope]);
  useEffect(()=>{const address = `${path}?${query}`;if (previous.current !== address) {previous.current = address;engine.current?.look();refreshPageReads(scope);}},[path,query,scope]);
  return null;
}
