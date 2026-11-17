'use client';
import { useSyncExternalStore } from 'react';
let running = false;
const listeners = new Set<()=>void>();
export function setPageWarmingRunning(value:boolean,ownsGlance=true) {const next = value && ownsGlance;if (running === next) return;running = next;listeners.forEach(run=>run());}
export function usePageWarmingRunning() {return useSyncExternalStore(run=>{listeners.add(run);return()=>{listeners.delete(run);};},()=>running,()=>false);}
