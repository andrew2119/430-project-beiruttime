'use client';
import { useEffect, useSyncExternalStore } from 'react';
import { request, ApiError } from '@/lib/api/client';
import { setAccessContext } from '@/shell/private-state';
import type { Role } from '@/registry-types';
import type { Session } from '@contracts/contracts-identity/accounts';

const base = '/api/web/v1/identity/v1/accounts';
let current: Session | null = null;
let generation = 0;
let restored = false;
let leaving = false;
let refreshFlight: Promise<Session | null> | null = null;
let signInFlight: Promise<Session> | null = null;
let restoreState: 'restoring' | 'signed-out' | 'unavailable' | 'authenticated' = 'restoring';
const listeners = new Set<() => void>();
let channel: BroadcastChannel | null = null;
function publish(session: Session | null) {
  current = session;
  restoreState = session ? 'authenticated' : 'signed-out';
  setAccessContext(session?.access_fingerprint ?? null, session?.principal.roles as Role[] | undefined);
  listeners.forEach(callback => callback());
}
function broadcast() { channel?.postMessage('signed-out'); }
function setup() {
  if (!channel && typeof BroadcastChannel !== 'undefined') {
    channel = new BroadcastChannel('bt-identity-v1');
    channel.onmessage = event => {
      if (event.data === 'signed-out') { generation++; leaving = true; publish(null); }
      if (event.data === 'session-changed') {
        generation++; leaving = false; restored = false; publish(null);
        void (refreshFlight ?? Promise.resolve()).catch(() => null).then(() => refreshSession()).catch(() => null);
      }
    };
  }
}
export function acceptSession(session: Session) {
  generation++; leaving = false; restored = true; setup(); publish(session); channel?.postMessage('session-changed');
}
export async function refreshSession(): Promise<Session | null> {
  if (leaving) return null;
  setup();
  if (!refreshFlight) {
    if (!current) { restoreState = 'restoring'; listeners.forEach(callback => callback()); }
    const expected = generation;
    const refresh = async () => {
      if (leaving || generation !== expected) return current;
      try {
        const session = await request<Session>(`${base}/refresh`, { method: 'POST' });
        if (!leaving && generation === expected) { restored = true; publish(session); }
        return generation === expected && !leaving ? current : null;
      } catch (error) {
        if (generation === expected && error instanceof ApiError && error.status === 401) { restored = true; publish(null); }
        if (error instanceof ApiError && error.status === 401) return null;
        if (generation === expected && !leaving) { restoreState = 'unavailable'; listeners.forEach(callback => callback()); }
        throw error;
      }
    };
    // CP F-11/S-02: one same-origin refresh admission, logout fences late answers.
    const coordinated = navigator.locks ? navigator.locks.request('bt-refresh-v1', refresh) as unknown as Promise<Session | null> : refresh();
    refreshFlight = coordinated.finally(() => { refreshFlight = null; });
  }
  return refreshFlight;
}
export async function beginSession(action: 'login' | 'register', body: string, key: string): Promise<Session> {
  if (signInFlight) throw new ApiError(409, 'session_pending', '');
  const expected = ++generation;
  leaving = false;
  const submit = async () => {
    if (generation !== expected || leaving) throw new ApiError(401, 'session_changed', '');
    const session = await request<Session>(`${base}/${action}`, { method:'POST', headers:{'Content-Type':'application/json','Idempotency-Key':key}, body });
    if (generation !== expected || leaving) throw new ApiError(401, 'session_changed', '');
    acceptSession(session);
    return session;
  };
  const admitted = async () => {
    await refreshFlight?.catch(() => null);
    return navigator.locks ? await navigator.locks.request('bt-refresh-v1', submit) : await submit();
  };
  signInFlight = admitted().finally(() => { signInFlight = null; });
  return signInFlight;
}
export async function signOut() {
  generation++; leaving = true; publish(null); broadcast();
  const revoke = () => request(`${base}/logout`, { method: 'POST' });
  // A prior refresh must finish before logout reads the cookie. Its answer cannot publish.
  await refreshFlight?.catch(() => null);
  await signInFlight?.catch(() => null);
  if (navigator.locks) await navigator.locks.request('bt-refresh-v1', revoke); else await revoke();
}
export function useSession() {
  const session = useSyncExternalStore(callback => { listeners.add(callback); return () => listeners.delete(callback); }, () => current, () => null);
  useEffect(() => { if (!restored && !leaving) void refreshSession().catch(() => { /* Feature renders explicit unavailable recovery. */ }); }, []);
  return session;
}
export function useSessionState() {
  return useSyncExternalStore(callback => { listeners.add(callback); return () => listeners.delete(callback); }, () => restoreState, () => 'restoring' as const);
}
export type AuthenticatedRequestInit = RequestInit & { accessFingerprint?: string };
export async function authenticatedRequest<T>(path: string, options: AuthenticatedRequestInit = {}): Promise<T> {
  const { accessFingerprint, ...init } = options;
  let session = current ?? await refreshSession();
  if (!session) throw new ApiError(401, 'unauthorized', '');
  const scope = accessFingerprint ?? session.access_fingerprint;
  const expected = generation;
  const invoke = async () => {
    if (generation !== expected || leaving || session!.access_fingerprint !== scope || current?.access_fingerprint !== scope) throw new ApiError(401, 'unauthorized', '');
    const headers = new Headers(init.headers);
    headers.set('Authorization', `Bearer ${session!.access_token}`);
    const result = await request<T>(path, { ...init, headers });
    if (generation !== expected || leaving || current?.access_fingerprint !== scope) throw new ApiError(401, 'unauthorized', '');
    return result;
  };
  try { return await invoke(); }
  catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401 || generation !== expected || leaving || current?.access_fingerprint !== scope) throw error;
    session = await refreshSession();
    if (!session) throw new ApiError(401, 'unauthorized', '');
    return invoke();
  }
}
export function safeReturnPath(value: string | null): string {
  if (!value || /[\\\u0000-\u0020#]/.test(value) || !value.startsWith('/') || value.startsWith('//')) return '/account';
  const candidate = value.split('?')[0];
  if (/(?:^|\/)\.{1,2}(?:\/|$)/.test(candidate) || /%(?:2f|5c|2e|0[0-9a-f]|1[0-9a-f]|7f)/i.test(candidate)) return '/account';
  let parsed: URL;
  try { parsed = new URL(value, 'https://beirut-time.invalid'); } catch { return '/account'; }
  if (parsed.origin !== 'https://beirut-time.invalid' || /%(?:2f|5c|2e|0[0-9a-f]|1[0-9a-f]|7f)/i.test(parsed.pathname)) return '/account';
  const path = (parsed.pathname.replace(/^\/(en|ar)(?=\/|$)/, '') || '/') + parsed.search;
  const allowed = ['/watches','/search','/buyer','/seller/listings','/seller/dashboard','/seller/verification','/seller/auctions','/checkout','/custom-requests','/consent','/account','/inbox','/customize','/services','/prices','/buying','/business','/business-intake','/operations/verification','/operations/dashboard','/operations/moderation'];
  return allowed.some(prefix => path === prefix || path.startsWith(prefix + '/') || path.startsWith(prefix + '?')) ? path : '/account';
}
export function signInHref(next: string, locale: 'en' | 'ar' = 'en') { return `/${locale}/account?next=${encodeURIComponent(safeReturnPath(next))}`; }
export const accountApi = base;
