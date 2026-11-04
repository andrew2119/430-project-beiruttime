'use client';
import { useSyncExternalStore } from 'react';
import type { Role } from '@/registry-types';
export type AccessContext = { fingerprint: string | null; roles: Role[] };
const signedOut: AccessContext = { fingerprint: null, roles: ['public'] };
let current = signedOut;
const listeners = new Set<() => void>();
export function publishAccessContext(next: AccessContext) { current = next; listeners.forEach(listener=>listener()); }
export function useAccessContext() { return useSyncExternalStore(listener=>{listeners.add(listener);return()=>listeners.delete(listener);},()=>current,()=>signedOut); }
